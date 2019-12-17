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
    QgsProject
)
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox, QApplication
from qgis.PyQt.QtCore import QSettings, Qt
from urllib.error import URLError

from .configuration_dialog import ConfigurationDialog
from .create_project_dialog import CreateProjectDialog
from .utils import find_qgis_files, create_mergin_client, ClientError, InvalidProject, changes_from_metadata

icon_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "images/FA_icons")


class MerginPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.data_item_provider = None
        self.actions = []
        self.menu = u'Mergin Plugin'

    def initGui(self):
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

    def __init__(self, parent, project):
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

        self.mc = self.parent().parent().mc

    def download(self):
        parent_dir = QFileDialog.getExistingDirectory(None, "Open Directory", "", QFileDialog.ShowDirsOnly)
        if not parent_dir:
            return

        target_dir = os.path.abspath(os.path.join(parent_dir, self.project['name']))
        settings = QSettings()

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.mc.download_project(self.project_name, target_dir)
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
        except (URLError, ValueError):
            QApplication.restoreOverrideCursor()
            msg = "Failed to download your project {}.\n" \
                  "Please make sure your Mergin settings are correct".format(self.project_name)
            QMessageBox.critical(None, 'Project download', msg, QMessageBox.Close)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            msg = "Failed to download your project {}.\n" \
                  "{}".format(self.project_name, str(e))
            QMessageBox.critical(None, 'Project download', msg, QMessageBox.Close)

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
            shutil.rmtree(self.path)
        settings = QSettings()
        settings.remove('Mergin/localProjects/{}/path'.format(self.project_name))
        self.path = None
        self.setIcon(QIcon(os.path.join(icon_path, "cloud-solid.svg")))

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

            msg = ''
            if sum(len(v) for v in pull_changes.values()):
                msg += pull_msg + "\n"
            if sum(len(v) for v in push_changes.values()):
                msg += push_msg
                msg += pretty_summary(push_changes_summary)
            if not msg:
                msg = "Project is already up-to-date"
            QMessageBox.information(None, 'Project status', msg, QMessageBox.Close)
        except (URLError, ClientError, InvalidProject) as e:
            msg = f"Failed to get status for project {self.project_name}:\n\n{str(e)}"
            QMessageBox.critical(None, 'Project status', msg, QMessageBox.Close)

    def sync_project(self):
        if not self.path:
            return

        try:
            pull_changes, push_changes, push_changes_summary = self.mc.project_status(self.path)
            if not sum(len(v) for v in list(pull_changes.values())+list(push_changes.values())):
                QMessageBox.information(None, 'Project sync', 'Project is already up-to-date', QMessageBox.Close)
                return

            QApplication.setOverrideCursor(Qt.WaitCursor)
            conflicts = self.mc.pull_project(self.path)
            if conflicts:
                msg = "Following conflicts between local and server version found: \n\n"
                for item in conflicts:
                    msg += item + "\n"
                msg += "\nYou may want to fix them before upload otherwise they will be uploaded as new files. " \
                       "Do you wish to proceed?"
                btn_reply = QMessageBox.question(None, 'Conflicts found', msg,
                                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if btn_reply == QMessageBox.No:
                    QApplication.restoreOverrideCursor()
                    return    
            
            self.mc.push_project(self.path)
            QApplication.restoreOverrideCursor()
            msg = "Mergin project {} synchronized successfully".format(self.project_name)
            QMessageBox.information(None, 'Project sync', msg, QMessageBox.Close)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            msg = "Failed to synchronize your project {}:\n\n{}".format(self.project_name, str(e))
            QMessageBox.critical(None, 'Project sync', msg, QMessageBox.Close)

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
            item = MerginProjectItem(self, project)
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
            action_create.triggered.connect(self.parent().create_project)
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

    def create_project(self):
        dlg = CreateProjectDialog()
        if dlg.exec_():
            dlg.create_project()
            self.depopulate()

    def actions(self, parent):
        action_configure = QAction(QIcon(os.path.join(icon_path, "cog-solid.svg")), "Configure", parent)
        action_configure.triggered.connect(self.configure)

        action_create = QAction(QIcon(os.path.join(icon_path, "plus-square-solid.svg")), "Create new project", parent)
        action_create.triggered.connect(self.create_project)
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

