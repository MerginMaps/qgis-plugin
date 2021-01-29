import os

from qgis.core import QgsProject
from qgis.utils import iface
from qgis.PyQt.QtWidgets import QMessageBox, QApplication
from qgis.PyQt.QtCore import QSettings, Qt
from urllib.error import URLError

from .sync_dialog import SyncDialog
from .utils import (
    ClientError,
    InvalidProject,
    LoginError,
    find_qgis_files,
    login_error_message,
    unhandled_exception_message,
    unsaved_project_check,
    write_project_variables,
)

from .mergin.merginproject import MerginProject
from .project_status_dialog import ProjectStatusDialog
from .validation import MerginProjectValidator

icon_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "images/FA_icons")


class MerginProjectsManager(object):
    """Class for managing Mergin projects in QGIS."""

    def __init__(self, mergin_client):
        self.mc = mergin_client
        self.iface = iface

    def set_current_project(self):
        """Find out if current QGIS project is a Mergin project and set it as current, eventually."""

    @staticmethod
    def unsaved_changes_check(project_dir):
        """
        Check if current project is the same as actually operated Mergin project and has some unsaved changes.
        """
        if QgsProject.instance().fileName() in find_qgis_files(project_dir):
            return True if unsaved_project_check() else False
        return True  # not a Mergin project

    def have_writing_permissions(self, project_name):
        """Check if user have writing rights to the project."""
        info = self.mc.project_info(project_name)
        username = self.mc.username()
        writersnames = info["access"]["writersnames"]
        return username in writersnames

    @staticmethod
    def open_project(project_dir):
        if not project_dir:
            return

        qgis_files = find_qgis_files(project_dir)
        if len(qgis_files) == 1:
            iface.addProject(qgis_files[0])
        else:
            msg = (
                "Selected project does not contain any QGIS project file"
                if len(qgis_files) == 0
                else "Plugin can only load project with single QGIS project file but {} found.".format(len(qgis_files))
            )
            QMessageBox.warning(None, "Load QGIS project", msg, QMessageBox.Close)

    def create_project(self, project_name, project_dir, is_public, namespace):
        """
        Create new Mergin project.
        If project_dir is None, we are creating empty project without upload.
        """

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.mc.create_project(project_name, is_public, namespace)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(None, "Create Project", "Failed to create Mergin project.\n" + str(e))
            return False

        QApplication.restoreOverrideCursor()

        if not project_dir:
            # not going to upload anything so just pop a "success" message and exit
            QMessageBox.information(
                None, "Create Project", "An empty project has been created on the server", QMessageBox.Close
            )
            return True

        # let's do initial upload of the project data

        mp = MerginProject(project_dir)
        full_project_name = "{}/{}".format(namespace, project_name)
        mp.metadata = {"name": full_project_name, "version": "v0", "files": []}
        if not mp.inspect_files():
            QMessageBox.warning(None, "Create Project", "The project directory is empty - nothing to upload.")
            return True

        dlg = SyncDialog()
        dlg.push_start(self.mc, project_dir, full_project_name)

        dlg.exec_()  # blocks until success, failure or cancellation

        if dlg.exception:
            # push failed for some reason
            if isinstance(dlg.exception, LoginError):
                login_error_message(dlg.exception)
            elif isinstance(dlg.exception, ClientError):
                QMessageBox.critical(None, "Project sync", "Client error: " + str(dlg.exception))
            else:
                unhandled_exception_message(
                    dlg.exception_details(),
                    "Project sync",
                    f"Failed to sync project {project_name} due to an unhandled exception.",
                )
            return True

        if not dlg.is_complete:
            # we were cancelled - but no need to show a message box about that...?
            return True

        settings = QSettings()
        settings.setValue("Mergin/localProjects/{}/path".format(full_project_name), project_dir)
        if (
            project_dir == QgsProject.instance().absolutePath()
            or project_dir + "/" in QgsProject.instance().absolutePath()
        ):
            write_project_variables(self.mc.username(), project_name, full_project_name, "v1")

        QMessageBox.information(
            None, "Create Project", "Mergin project created and uploaded successfully", QMessageBox.Close
        )

        return True

    def project_status(self, project_dir):
        if project_dir is None:
            return
        if not unsaved_project_check():
            return

        mp = MerginProject(project_dir)
        try:
            project_name = mp.metadata["name"]
        except InvalidProject as e:
            msg = f"Failed to get project status:\n\n{str(e)}"
            QMessageBox.critical(None, "Project status", msg, QMessageBox.Close)
            return
        validator = MerginProjectValidator(mp, self.mc)
        validation_results = validator.run_checks()
        try:
            pull_changes, push_changes, push_changes_summary = self.mc.project_status(project_dir)
            # if not sum(len(v) for v in list(pull_changes.values()) + list(push_changes.values())):
            #     QMessageBox.information(None, "Project status", "Project is already up-to-date", QMessageBox.Close)
            # else:
            dlg = ProjectStatusDialog(
                pull_changes,
                push_changes,
                push_changes_summary,
                self.have_writing_permissions(project_name),
                validation_results,
            )
            dlg.exec_()

        except (URLError, ClientError, InvalidProject) as e:
            msg = f"Failed to get status for project {project_name}:\n\n{str(e)}"
            QMessageBox.critical(None, "Project status", msg, QMessageBox.Close)
        except LoginError as e:
            login_error_message(e)

    def sync_project(self, project_dir, project_name=None):
        if not project_dir:
            return
        if not self.unsaved_changes_check(project_dir):
            return
        if project_name is None:
            mp = MerginProject(project_dir)
            try:
                project_name = mp.metadata["name"]
            except InvalidProject as e:
                msg = f"Failed to sync project:\n\n{str(e)}"
                QMessageBox.critical(None, "Project syncing", msg, QMessageBox.Close)
                return

        pull_changes, push_changes, push_changes_summary = self.mc.project_status(project_dir)
        if not sum(len(v) for v in list(pull_changes.values()) + list(push_changes.values())):
            QMessageBox.information(None, "Project sync", "Project is already up-to-date", QMessageBox.Close)
            return

        dlg = SyncDialog()
        dlg.pull_start(self.mc, project_dir, project_name)

        dlg.exec_()  # blocks until success, failure or cancellation

        if dlg.exception:
            # pull failed for some reason
            if isinstance(dlg.exception, LoginError):
                login_error_message(dlg.exception)
            elif isinstance(dlg.exception, ClientError):
                QMessageBox.critical(None, "Project sync", "Client error: " + str(dlg.exception))
            else:
                unhandled_exception_message(
                    dlg.exception_details(),
                    "Project sync",
                    f"Failed to sync project {project_name} due to an unhandled exception.",
                )
            return

        if dlg.pull_conflicts:
            msg = "Following conflicts between local and server version found: \n\n"
            for item in dlg.pull_conflicts:
                msg += item + "\n"
            msg += (
                "\nYou may want to fix them before upload otherwise they will be uploaded as new files. "
                "Do you wish to proceed?"
            )
            btn_reply = QMessageBox.question(
                None, "Conflicts found", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if btn_reply == QMessageBox.No:
                QApplication.restoreOverrideCursor()
                return

        if not dlg.is_complete:
            # we were cancelled
            return

        # pull finished, start push
        if any(push_changes.values()) and not self.have_writing_permissions(project_name):
            QMessageBox.information(
                None, "Project sync", "You have no writing rights to this project", QMessageBox.Close
            )
            return
        dlg = SyncDialog()
        dlg.push_start(self.mc, project_dir, project_name)

        dlg.exec_()  # blocks until success, failure or cancellation

        self.open_project(project_dir)  # TODO: only reload project if we pulled a newer version

        if dlg.exception:
            # push failed for some reason
            if isinstance(dlg.exception, LoginError):
                login_error_message(dlg.exception)
            elif isinstance(dlg.exception, ClientError):
                QMessageBox.critical(None, "Project sync", "Client error: " + str(dlg.exception))
            else:
                unhandled_exception_message(
                    dlg.exception_details(),
                    "Project sync",
                    f"Failed to sync project {project_name} due to an unhandled exception.",
                )
            return

        if dlg.is_complete:
            # TODO: report success only when we have actually done anything
            msg = "Mergin project {} synchronized successfully".format(project_name)
            QMessageBox.information(None, "Project sync", msg, QMessageBox.Close)
        else:
            # we were cancelled - but no need to show a message box about that...?
            pass

