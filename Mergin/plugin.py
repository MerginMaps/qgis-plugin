# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited

import sip
import os
import shutil
import posixpath
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsApplication,
    QgsDataItem,
    QgsDataCollectionItem,
    QgsErrorItem,
    QgsDataItemProvider,
    QgsDataProvider,
    QgsProject,
    QgsVectorLayer)
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox, QApplication
from qgis.PyQt.QtCore import QSettings, Qt
from urllib.error import URLError

from .configuration_dialog import ConfigurationDialog
from .create_project_dialog import CreateProjectDialog
from .sync_dialog import SyncDialog
from .utils import find_qgis_files, create_mergin_client, ClientError, InvalidProject, changes_from_metadata, LoginError, \
    get_mergin_auth

from .mergin.merginproject import MerginProject

icon_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "images/FA_icons")


class MerginPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.data_item_provider = None
        self.actions = []
        self.menu = u'Mergin Plugin'

    def initGui(self):

        # This is a quick fix for a bad crasher for users that have set up master password for their
        # storage of authentication configurations. What would happen is that in a worker thread,
        # QGIS browser model would start populating Mergin data items which would want to query Mergin
        # server and thus request auth info - but as this would be done in a background thread,
        # things will get horribly wrong when QGIS tries to display GUI and the app would crash.
        # Triggering auth request to QGIS auth framework already at this point will make sure that
        # the dialog asking for master password is started from the main thread -> no crash.
        get_mergin_auth()

        self.data_item_provider = DataItemProvider()
        QgsApplication.instance().dataItemProviderRegistry().addProvider(self.data_item_provider)
        # related to https://github.com/lutraconsulting/qgis-mergin-plugin/issues/3
        # if self.iface.browserModel().initialized():
        #     self.iface.browserModel().reload()

    def unload(self):
        QgsApplication.instance().dataItemProviderRegistry().removeProvider(self.data_item_provider)
        self.data_item_provider = None
        # this is crashing qgis on exit
        # self.iface.browserModel().reload()


def pretty_summary(summary):
    msg = ""
    for k, v in summary.items():
        msg += "\nDetails " + k
        msg += "".join("\n layer name - " + d["table"] + ": inserted: " + str(d["insert"]) + ", modified: " +
                            str(d["update"]) + ", deleted: " + str(d["delete"]) for d in v['geodiff_summary'] if d["table"] != "gpkg_contents")
    return msg


class MerginProjectItem(QgsDataItem):
    """ Data item to represent a Mergin project. """

    def __init__(self, parent, project, mc):
        self.project = project
        self.project_name = posixpath.join(project['namespace'], project['name'])  # we need posix path for server API calls
        QgsDataItem.__init__(self, QgsDataItem.Collection, parent, self.project_name, "/Mergin/" + self.project_name)
        settings = QSettings()
        self.path = settings.value('Mergin/localProjects/{}/path'.format(self.project_name), None)
        # check local project dir was not unintentionally removed
        if self.path:
            if not os.path.exists(self.path):
                self.path = None
        
        if self.path:
            self.setIcon(QIcon(os.path.join(icon_path, "folder-solid.svg")))
        else:
            self.setIcon(QIcon(os.path.join(icon_path, "cloud-solid.svg")))

        self.mc = mc

    def _login_error_message(self, e):
        QgsApplication.messageLog().logMessage(f"Mergin plugin: {str(e)}")
        msg = "<font color=red>Security token has been expired, failed to renew. Check your username and password </font>"
        QMessageBox.critical(None, 'Login failed', msg, QMessageBox.Close)

    def _unhandled_exception_message(self, error_details, dialog_title, error_text):
        msg = error_text + "<p>This should not happen, " \
              "<a href=\"https://github.com/lutraconsulting/qgis-mergin-plugin/issues\">" \
              "please report the problem</a>."
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle(dialog_title)
        box.setText(msg)
        box.setDetailedText(error_details)
        box.exec_()

    def download(self):
        settings = QSettings()

        last_parent_dir = settings.value('Mergin/lastUsedDownloadDir', '')

        parent_dir = QFileDialog.getExistingDirectory(None, "Open Directory", last_parent_dir, QFileDialog.ShowDirsOnly)
        if not parent_dir:
            return

        settings.setValue('Mergin/lastUsedDownloadDir', parent_dir)

        target_dir = os.path.abspath(os.path.join(parent_dir, self.project['name']))

        if os.path.exists(target_dir):
            QMessageBox.warning(None, "Download Project", "The target directory already exists:\n"+target_dir+
                                      "\n\nPlease select a different directory.")
            return

        dlg = SyncDialog()
        dlg.download_start(self.mc, target_dir, self.project_name)

        dlg.exec_()  # blocks until completion / failure / cancellation

        if dlg.exception:
            if isinstance(dlg.exception, (URLError, ValueError)):
                QgsApplication.messageLog().logMessage("Mergin plugin: " + str(dlg.exception))
                msg = "Failed to download your project {}.\n" \
                      "Please make sure your Mergin settings are correct".format(self.project_name)
                QMessageBox.critical(None, 'Project download', msg, QMessageBox.Close)
            elif isinstance(dlg.exception, LoginError):
                self._login_error_message(dlg.exception)
            else:
                self._unhandled_exception_message(
                    dlg.exception_details(), "Project download",
                    f"Failed to download project {self.project_name} due to an unhandled exception.")
            return

        if not dlg.is_complete:
            return   # either it has been cancelled or an error has been thrown

        settings.setValue('Mergin/localProjects/{}/path'.format(self.project_name), target_dir)
        self.path = target_dir
        self.setIcon(QIcon(os.path.join(icon_path, "folder-solid.svg")))
        QApplication.restoreOverrideCursor()

        msg = "Your project {} has been successfully downloaded. " \
              "Do you want to open project file?".format(self.project_name)
        btn_reply = QMessageBox.question(None, 'Project download', msg,
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if btn_reply == QMessageBox.Yes:
            self.open_project()

    def remove_local_project(self):
        if not self.path:
            return

        msg = "Your local changes will be lost. Make sure your project is synchronised with server. \n\n" \
              "Do you want to proceed?".format(self.project_name)
        btn_reply = QMessageBox.question(None, 'Remove local project', msg,
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if btn_reply == QMessageBox.No:
            return

        if os.path.exists(self.path):
            try:
                shutil.rmtree(self.path)
            except PermissionError as e:
                QgsApplication.messageLog().logMessage(f"Mergin plugin: {str(e)}")
                msg = "Failed to delete your project {} because is open.\n" \
                      "Close project and check if it is not open in another application.".format(self.project_name)
                QMessageBox.critical(None, 'Project delete', msg, QMessageBox.Close)
                return

        settings = QSettings()
        settings.remove('Mergin/localProjects/{}/path'.format(self.project_name))
        self.path = None
        self.setIcon(QIcon(os.path.join(icon_path, "cloud-solid.svg")))

    def _unsaved_changes_check(self):
        """Check if current project is same as actually operated mergin project
        and if there are some unsaved changes.
        :return: true if previous method should continue, false otherwise
        :type: boolean
        """
        qgis_files = find_qgis_files(self.path)
        if QgsProject.instance().fileName() in qgis_files:
            if any([type(layer) is QgsVectorLayer and layer.isModified() for layer in
                     QgsProject.instance().mapLayers().values()]) or QgsProject.instance().isDirty():
                msg = "There are some unsaved changes. Do you want save it before continue?"
                btn_reply = QMessageBox.warning(None, 'Stop editing', msg,
                                                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)

                if btn_reply == QMessageBox.Yes:
                    if QgsProject.instance().isDirty():
                        QgsProject.instance().write()
                    for layer in QgsProject.instance().mapLayers().values():
                        if type(layer) is QgsVectorLayer and layer.isModified():
                            layer.commitChanges()
                    return True
                elif btn_reply == QMessageBox.No:
                    return True
                else:
                    return False
            return True
        return True

    def _have_writing_permissions(self):
        """Check if user have writing rights to the project."""
        info = self.mc.project_info(self.project_name)
        username = self.mc.username()
        writersnames = info["access"]["writersnames"]
        return username in writersnames

    def open_project(self):
        if not self.path:
            return 

        qgis_files = find_qgis_files(self.path)
        if len(qgis_files) == 1:
            QgsProject.instance().read(qgis_files[0])
        else:
            msg = "Selected project does not contain any QGIS project file" if len(qgis_files) == 0 else "Plugin can only load project with single QGIS project file but {} found.".format(len(qgis_files))
            QMessageBox.warning(None, 'Load QGIS project', msg, QMessageBox.Close)

    def project_status(self):
        if not self.path:
            return

        if not self._unsaved_changes_check():
            return

        try:
            pull_changes, push_changes, push_changes_summary = self.mc.project_status(self.path)
            pull_added, pull_removed, pull_updated, pull_renamed = changes_from_metadata(pull_changes)
            push_added, push_removed, push_updated, push_renamed = changes_from_metadata(push_changes)

            pull_msg = "Pending changes from the latest server version: \n"
            if pull_added:
                pull_msg += f"added: {pull_added} \n"
            if pull_removed:
                pull_msg += f"removed: {pull_removed} \n"
            if pull_updated:
                pull_msg += f"updated: {pull_updated} \n"
            if pull_renamed:
                pull_msg += f"renamed: {pull_renamed} \n"

            push_msg = "These local changes have been found: \n"
            if push_added:
                push_msg += f"added: {push_added} \n"
            if push_removed:
                push_msg += f"removed: {push_removed} \n"
            if push_updated:
                push_msg += f"updated: {push_updated} \n"
            if push_renamed:
                push_msg += f"renamed: {push_renamed} \n"

            files_to_replace = ", ".join([file["path"] for file in push_changes["updated"] if "diff" not in file and ".gpkg" in file['path']])

            msg = ''
            if sum(len(v) for v in pull_changes.values()):
                msg += pull_msg + "\n"
            if sum(len(v) for v in push_changes.values()):
                msg += push_msg
                msg += pretty_summary(push_changes_summary)
                msg += f"\nUnable to compare some of the modified local files with their server version - we will have to upload the whole file (history of the files will be lost): {files_to_replace}" if files_to_replace else ""
                if not self._have_writing_permissions():
                    msg += f"\n\nWARNING: You don't have writing permissions to this project. Changes won't be synced!"

            if not msg:
                msg = "Project is already up-to-date"
            QMessageBox.information(None, 'Project status', msg, QMessageBox.Close)
        except (URLError, ClientError, InvalidProject) as e:
            msg = f"Failed to get status for project {self.project_name}:\n\n{str(e)}"
            QMessageBox.critical(None, 'Project status', msg, QMessageBox.Close)
        except LoginError as e:
            self._login_error_message(e)

    def sync_project(self):
        if not self.path:
            return

        if not self._unsaved_changes_check():
            return

        pull_changes, push_changes, push_changes_summary = self.mc.project_status(self.path)
        if not sum(len(v) for v in list(pull_changes.values())+list(push_changes.values())):
            QMessageBox.information(None, 'Project sync', 'Project is already up-to-date', QMessageBox.Close)
            return

        dlg = SyncDialog()
        dlg.pull_start(self.mc, self.path, self.project_name)

        dlg.exec_()  # blocks until success, failure or cancellation

        if dlg.exception:
            # pull failed for some reason
            if isinstance(dlg.exception, LoginError):
                self._login_error_message(dlg.exception)
            elif isinstance(dlg.exception, ClientError):
                QMessageBox.critical(None, "Project sync", "Client error: " + str(dlg.exception))
            else:
                self._unhandled_exception_message(
                    dlg.exception_details(), "Project sync",
                    f"Failed to sync project {self.project_name} due to an unhandled exception.")
            return

        if dlg.pull_conflicts:
            msg = "Following conflicts between local and server version found: \n\n"
            for item in dlg.pull_conflicts:
                msg += item + "\n"
            msg += "\nYou may want to fix them before upload otherwise they will be uploaded as new files. " \
                   "Do you wish to proceed?"
            btn_reply = QMessageBox.question(None, 'Conflicts found', msg,
                                             QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if btn_reply == QMessageBox.No:
                QApplication.restoreOverrideCursor()
                return

        if not dlg.is_complete:
            # we were cancelled
            return

        # pull finished, start push
        if any(push_changes.values()) and not self._have_writing_permissions():
            QMessageBox.information(None, "Project sync", "You have no writing rights to this project",
                                    QMessageBox.Close)
            return
        dlg = SyncDialog()
        dlg.push_start(self.mc, self.path, self.project_name)

        dlg.exec_()  # blocks until success, failure or cancellation

        self._reload_project()  # TODO: only reload project if we pulled a newer version

        if dlg.exception:
            # push failed for some reason
            if isinstance(dlg.exception, LoginError):
                self._login_error_message(dlg.exception)
            elif isinstance(dlg.exception, ClientError):
                QMessageBox.critical(None, "Project sync", "Client error: " + str(dlg.exception))
            else:
                self._unhandled_exception_message(
                    dlg.exception_details(), "Project sync",
                    f"Failed to sync project {self.project_name} due to an unhandled exception.")
            return

        if dlg.is_complete:
            # TODO: report success only when we have actually done anything
            msg = "Mergin project {} synchronized successfully".format(self.project_name)
            QMessageBox.information(None, 'Project sync', msg, QMessageBox.Close)
        else:
            # we were cancelled - but no need to show a message box about that...?
            pass

    def _reload_project(self):
        """ This will forcefully reload the QGIS project because the project (or its data) may have changed """
        qgis_files = find_qgis_files(self.path)
        if QgsProject.instance().fileName() in qgis_files:
            QgsProject.instance().read()

    def remove_remote_project(self):
        msg = "Do you really want to remove project {} from server?".format(self.project_name)
        btn_reply = QMessageBox.question(None, 'Remove project', msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if btn_reply == QMessageBox.No:
            return

        try:
            self.mc.delete_project(self.project_name)
            msg = "Mergin project removed successfully."
            QMessageBox.information(None, 'Remove project', msg, QMessageBox.Close)
            root_item = self.parent().parent()
            groups = root_item.children()
            for g in groups:
                g.refresh()
        except (URLError, ClientError) as e:
            msg = "Failed to remove project {}:\n\n{}".format(self.project_name, str(e))
            QMessageBox.critical(None, 'Remove project', msg, QMessageBox.Close)
        except LoginError as e:
            self._login_error_message(e)

    def actions(self, parent):
        action_download = QAction(QIcon(os.path.join(icon_path, "cloud-download-alt-solid.svg")), "Download", parent)
        action_download.triggered.connect(self.download)

        action_remove_local = QAction(QIcon(os.path.join(icon_path, "trash-solid.svg")), "Remove locally", parent)
        action_remove_local.triggered.connect(self.remove_local_project)

        action_open_project = QAction("Open QGIS project", parent)
        action_open_project.triggered.connect(self.open_project)

        action_sync_project = QAction(QIcon(os.path.join(icon_path, "sync-solid.svg")), "Synchronize", parent)
        action_sync_project.triggered.connect(self.sync_project)

        action_remove_remote = QAction(QIcon(os.path.join(icon_path, "trash-alt-solid.svg")), "Remove from server", parent)
        action_remove_remote.triggered.connect(self.remove_remote_project)

        action_status = QAction(QIcon(os.path.join(icon_path, "info-circle-solid.svg")), "Status", parent)
        action_status.triggered.connect(self.project_status)

        if self.path:
            actions = [action_open_project, action_status, action_sync_project, action_remove_local]
        else:
            actions = [action_download]
            if self.project['permissions']['delete']:
                actions.append(action_remove_remote)
        return actions


class MerginGroupItem(QgsDataCollectionItem):
    """ Mergin group data item. Contains filtered list of Mergin projects. """

    def __init__(self, parent, grp_name, grp_filter, icon, order):
        QgsDataCollectionItem.__init__(self, parent, grp_name, "/Mergin" + grp_name)
        self.filter = grp_filter
        self.setIcon(QIcon(os.path.join(icon_path, icon)))
        self.setSortKey(order)

    def createChildren(self):
        mc = self.parent().mc
        if not mc:
            error_item = QgsErrorItem(self, "Failed to login please check the configuration", "/Mergin/error")
            sip.transferto(error_item, self)
            return [error_item]
        try:
            projects = mc.projects_list(flag=self.filter)
        except URLError:
            error_item = QgsErrorItem(self, "Failed to get projects from server", "/Mergin/error")
            sip.transferto(error_item, self)
            return [error_item]
        except Exception as err:
            error_item = QgsErrorItem(self, "Error: {}".format(str(err)), "/Mergin/error")
            sip.transferto(error_item, self)
            return [error_item]

        items = []
        for project in projects:
            item = MerginProjectItem(self, project, mc)
            item.setState(QgsDataItem.Populated)  # make it non-expandable
            sip.transferto(item, self)
            items.append(item)
        return items

    def actions(self, parent):
        action_refresh = QAction(QIcon(os.path.join(icon_path, "redo-solid.svg")), "Reload", parent)
        action_refresh.triggered.connect(self.refresh)
        actions = [action_refresh]
        if self.name() == "My projects":
            action_create = QAction(
                QIcon(os.path.join(icon_path, "plus-square-solid.svg")),
                "Create new project",
                parent)
            action_create.triggered.connect(self.parent().show_create_project_dialog)
            actions.append(action_create)
        return actions


class MerginRootItem(QgsDataCollectionItem):
    """ Mergin root data containing project groups item with configuration dialog. """

    def __init__(self):
        QgsDataCollectionItem.__init__(self, None, "Mergin", "/Mergin")
        self.setIcon(QIcon(os.path.join(os.path.dirname(os.path.realpath(__file__)), "images/icon.png")))
        self.mc = None
        self.error = ''
        try:
            self.mc = create_mergin_client()
        except (URLError, ClientError):
            self.error = "Plugin not configured or \n QGIS master password not set up"
        except Exception as err:
            self.error = "Error: {}".format(str(err))

    def createChildren(self):
        if not self.mc and self.error:
            error_item = QgsErrorItem(self, self.error, "/Mergin/error")
            error_item.setIcon(QIcon(os.path.join(icon_path, "exclamation-triangle-solid.svg")))
            sip.transferto(error_item, self)
            return [error_item]

        items = []
        my_projects = MerginGroupItem(self, "My projects", "created", "user-solid.svg", 1)
        my_projects.setState(QgsDataItem.Populated)
        my_projects.refresh()
        sip.transferto(my_projects, self)
        items.append(my_projects)

        shared_projects = MerginGroupItem(self, "Shared with me", "shared", "user-friends-solid.svg", 2)
        shared_projects.setState(QgsDataItem.Populated)
        shared_projects.refresh()
        sip.transferto(shared_projects, self)
        items.append(shared_projects)

        all_projects = MerginGroupItem(self, "Explore", None, "list-solid.svg", 3)
        all_projects.setState(QgsDataItem.Populated)
        all_projects.refresh()
        sip.transferto(all_projects, self)
        items.append(all_projects)

        return items

    def configure(self):
        dlg = ConfigurationDialog()
        if dlg.exec_():
            self.mc = dlg.writeSettings()
            self.depopulate()

    def show_create_project_dialog(self):
        dlg = CreateProjectDialog()
        if not dlg.exec_():
            return  # cancelled

        self.create_project(dlg.project_name, dlg.project_dir, dlg.is_public)

    def create_project(self, project_name, project_dir, is_public):
        """ After user has selected project name, this function does the communication.
        If project_dir is None, we are creating empty project without upload.
        """

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.mc.create_project(project_name, is_public)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(None, 'Create Project', "Failed to create Mergin project.\n" + str(e))
            return

        QApplication.restoreOverrideCursor()

        if not project_dir:
            # not going to upload anything so just pop a "success" message and exit
            self.depopulate()
            QMessageBox.information(None, 'Create Project', "An empty project has been created on the server", QMessageBox.Close)
            return

        ## let's do initial upload of the project data

        mp = MerginProject(project_dir)
        full_project_name = "{}/{}".format(self.mc.username(), project_name)
        mp.metadata = { "name": full_project_name, "version": "v0", "files": [] }
        if not mp.inspect_files():
            self.depopulate()
            QMessageBox.warning(None, "Create Project", "The project directory is empty - nothing to upload.")
            return

        dlg = SyncDialog()
        dlg.push_start(self.mc, project_dir, full_project_name)

        dlg.exec_()  # blocks until success, failure or cancellation

        if dlg.exception:
            # push failed for some reason
            if isinstance(dlg.exception, LoginError):
                self._login_error_message(dlg.exception)
            elif isinstance(dlg.exception, ClientError):
                QMessageBox.critical(None, "Project sync", "Client error: " + str(dlg.exception))
            else:
                self._unhandled_exception_message(
                    dlg.exception_details(), "Project sync",
                    f"Failed to sync project {project_name} due to an unhandled exception.")
            return

        if not dlg.is_complete:
            # we were cancelled - but no need to show a message box about that...?
            return

        settings = QSettings()
        settings.setValue('Mergin/localProjects/{}/path'.format(full_project_name), project_dir)

        self.depopulate()  # make sure the project item has the link between remote and local project we have just added

        QMessageBox.information(None, 'Create Project', "Mergin project created and uploaded successfully", QMessageBox.Close)

    def actions(self, parent):
        action_configure = QAction(QIcon(os.path.join(icon_path, "cog-solid.svg")), "Configure", parent)
        action_configure.triggered.connect(self.configure)

        action_create = QAction(QIcon(os.path.join(icon_path, "plus-square-solid.svg")), "Create new project", parent)
        action_create.triggered.connect(self.show_create_project_dialog)
        actions = [action_configure]
        if self.mc:
            actions.append(action_create)
        return actions


class DataItemProvider(QgsDataItemProvider):

    def __init__(self):
        QgsDataItemProvider.__init__(self)

    def name(self):
        return "MerginProvider"

    def capabilities(self):
        return QgsDataProvider.Net

    def createDataItem(self, path, parentItem):
        if not parentItem:
            ri = MerginRootItem()
            sip.transferto(ri, None)
            return ri
        else:
            return None

