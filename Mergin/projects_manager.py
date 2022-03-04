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
    get_local_mergin_projects_info,
    LoginError,
    find_qgis_files,
    login_error_message,
    same_dir,
    send_logs,
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
        server_url = self.mc.url.rstrip("/")
        settings.setValue(f"Mergin/localProjects/{full_project_name}/path", project_dir)
        settings.setValue(f"Mergin/localProjects/{full_project_name}/server", server_url)
        if (
            project_dir == QgsProject.instance().absolutePath()
            or project_dir + "/" in QgsProject.instance().absolutePath()
        ):
            write_project_variables(self.mc.username(), project_name, full_project_name, "v1", server_url)

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
        if not self.check_project_server(project_dir):
            return
        validator = MerginProjectValidator(mp)
        validation_results = validator.run_checks()
        try:
            pull_changes, push_changes, push_changes_summary = self.mc.project_status(project_dir)
            dlg = ProjectStatusDialog(
                pull_changes,
                push_changes,
                push_changes_summary,
                self.have_writing_permissions(project_name),
                validation_results,
                mp
            )
            dlg.exec_()

        except (URLError, ClientError, InvalidProject) as e:
            msg = f"Failed to get status for project {project_name}:\n\n{str(e)}"
            QMessageBox.critical(None, "Project status", msg, QMessageBox.Close)
        except LoginError as e:
            login_error_message(e)

    def check_project_server(self, project_dir, inform_user=True):
        """Check if the project was created for current plugin Mergin server."""
        proj_server = None
        for path, owner, name, server in get_local_mergin_projects_info():
            if not same_dir(path, project_dir):
                continue
            proj_server = server
            break
        if proj_server is not None and proj_server.rstrip("/") == self.mc.url.rstrip("/"):
            return True
        if inform_user:
            info = f"Current project was created for another Mergin server:\n{proj_server}\n\n"
            info += "You need to reconfigure Mergin plugin to synchronise the project."
            QMessageBox.critical(None, "Mergin", info)
        return False

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
        if not self.check_project_server(project_dir):
            return
        try:
            pull_changes, push_changes, push_changes_summary = self.mc.project_status(project_dir)
        except InvalidProject as e:
            msg = f"Project is invalid:\n\n{str(e)}"
            QMessageBox.critical(None, "Project syncing", msg, QMessageBox.Close)
            return

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
            msg = "We have detected conflicting changes between your local copy and " + \
                  "the server that could not be resolved automatically. It is recommended " + \
                  "to manually reconcile your local changes (which have been moved to " + \
                  "conflicted copies) before running sync again.\n" + \
                  "Following conflicted copies were created:\n\n"
            for item in dlg.pull_conflicts:
                msg += item + "\n"
            msg += (
                "\nTo learn what are the conflicts about and how to avoid them please check our"
                "<a href='https://merginmaps.com/docs/manage/missing-data/#there-are-conflict-files-in-the-folder'>documentation</a>.\n\n"
            )
            msg_box = QMessageBox()
            msgBox.setWindowTitle("Conflicts found")
            msgBox.setIcon(QMessageBox.Warning)
            msgBox.setTextFormat(Qt.RichText)
            msgBox.setStandardButtons(QMessageBox.Ok)
            msgBox.setText(msg)
            msgBox.exec_()
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

        qgis_proj_filename = QgsProject.instance().fileName()
        qgis_proj_basename = os.path.basename(qgis_proj_filename)
        qgis_proj_changed = False
        for updated in pull_changes["updated"]:
            if updated["path"] == qgis_proj_basename:
                qgis_proj_changed = True
                break
        if qgis_proj_filename in find_qgis_files(project_dir) and qgis_proj_changed:
            self.open_project(project_dir)

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
            # clear canvas cache so any changes become immediately visible to users
            self.iface.mapCanvas().clearCache()
            self.iface.mapCanvas().refresh()
        else:
            # we were cancelled - but no need to show a message box about that...?
            pass

    def submit_logs(self, project_dir):
        logs_path = os.path.join(project_dir, ".mergin", "client-log.txt")
        msg = (
            "This action will send a diagnostic log to the developers. "
            "Use this option when you encounter synchronization issues, as the log is "
            "very useful to determine the exact cause of the problem.\n\n"
            "The log does not contain any of your data, only file names. It can be found here:\n"
            "{}\n\nIt would be useful if you also send a mail to info@lutraconsulting.co.uk "
            "and briefly describe the problem to add more context to the diagnostic log.\n\n"
            "Please click OK if you want to proceed.".format(logs_path)
        )

        btn_reply = QMessageBox.question(None, "Submit diagnostic logs", msg, QMessageBox.Ok | QMessageBox.Cancel)
        if btn_reply != QMessageBox.Ok:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        log_file_name, error = send_logs(self.mc.username(), logs_path)
        QApplication.restoreOverrideCursor()

        if error:
            QMessageBox.warning(
                None, "Submit diagnostic logs", "Sending of diagnostic logs failed!\n\n{}".format(error)
            )
            return
        QMessageBox.information(
            None,
            "Submit diagnostic logs",
            "Diagnostic logs successfully submitted - thank you!\n\n{}".format(log_file_name),
            QMessageBox.Close,
        )

    def get_mergin_browser_groups(self):
        """
        Return browser tree items of Mergin provider. These should be the 3 projects groups, or Error item, if
        the plugin is not properly configured.
        """
        browser_model = self.iface.browserModel()
        root_idx = browser_model.findPath("Mergin")
        if not root_idx.isValid():
            return {}
        group_items = [browser_model.dataItem(browser_model.index(i, 0, parent=root_idx)) for i in range(3)]
        return {i.path().replace("/Mergin", ""): i for i in group_items}
