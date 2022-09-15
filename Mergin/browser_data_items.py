# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited

from math import floor
import sip
import os
import shutil
from pathlib import Path
import posixpath
from qgis.PyQt.QtCore import pyqtSignal, QTimer, QUrl, QSettings, Qt
from qgis.PyQt.QtGui import QIcon, QDesktopServices, QPixmap
from qgis.core import (
    QgsApplication,
    QgsDataCollectionItem,
    QgsDataItem,
    QgsDataItemProvider,
    QgsDataProvider,
    QgsDirectoryItem,
    QgsErrorItem,
    QgsExpressionContextUtils,
    QgsProject,
    QgsMapLayer,
    QgsProviderRegistry,
    Qgis,
)
from qgis.utils import iface
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox, QDockWidget
from urllib.error import URLError

from .configuration_dialog import ConfigurationDialog
from .workspace_selection_dialog import WorkspaceSelectionDialog
from .create_project_wizard import NewMerginProjectWizard
from .clone_project_dialog import CloneProjectDialog
from .diff_dialog import DiffViewerDialog
from .project_settings_widget import MerginProjectConfigFactory
from .projects_manager import MerginProjectsManager
from .sync_dialog import SyncDialog
from .utils import (
    ClientError,
    LoginError,
    check_mergin_subdirs,
    create_mergin_client,
    find_qgis_files,
    get_mergin_auth,
    icon_path,
    is_number,
    login_error_message,
    mergin_project_local_path,
    PROJS_PER_PAGE,
    remove_project_variables,
    same_dir,
    unhandled_exception_message,
    unsaved_project_check,
    UnsavedChangesStrategy,
)

from .mergin.merginproject import MerginProject
from .processing.provider import MerginProvider


class DataItemProvider(QgsDataItemProvider):
    def __init__(self, plugin):
        QgsDataItemProvider.__init__(self)
        self.root_item = None
        self.plugin = plugin

    def name(self):
        return "MerginProvider"

    def capabilities(self):
        return QgsDataProvider.Net

    def createDataItem(self, path, parentItem):
        if not parentItem:
            ri = MerginRootItemLegacy(self.plugin)
            sip.transferto(ri, None)
            self.root_item = ri
            return ri
        else:
            return None


class MerginRootItemBase(QgsDataCollectionItem):
    """Mergin root data containing project groups item with configuration dialog."""

    local_project_removed = pyqtSignal()

    def __init__(self, plugin=None):
        QgsDataCollectionItem.__init__(self, None, "Mergin Maps", "Mergin Maps")
        self.setIcon(QIcon(icon_path("mm_icon_positive_no_padding.svg")))
        self.plugin = plugin
        self.project_manager = plugin.manager
        self.mc = self.project_manager.mc if self.project_manager is not None else None
        self.error = ""
        self.wizard = None

    def update_client_and_manager(self, mc=None, manager=None, err=None):
        """Update Mergin client and project manager - used when starting or after a config change."""
        self.mc = mc
        self.project_manager = manager
        self.error = err
        self.depopulate()

    def actions(self, parent):
        action_configure = QAction(QIcon(icon_path("settings.svg")), "Configure", parent)
        action_configure.triggered.connect(self.plugin.configure)

        action_create = QAction(QIcon(icon_path("square-plus.svg")), "Create new project", parent)
        action_create.triggered.connect(self.plugin.create_new_project)
        actions = [action_configure]
        if self.mc:
            actions.append(action_create)
        return actions


class MerginRootItemLegacy(MerginRootItemBase):
    def __init__(self, plugin=None):
        MerginRootItemBase.__init__(self, plugin)

    def createChildren(self):
        if self.error or self.mc is None:
            self.error = self.error if self.error else "Not configured!"
            error_item = QgsErrorItem(self, self.error, "Mergin/error")
            error_item.setIcon(QIcon(icon_path("alert-triangle.svg")))
            sip.transferto(error_item, self)
            return [error_item]

        items = []
        my_projects = MerginGroupItem(self, "My projects", "created", "user.svg", 1, self.plugin)
        my_projects.setState(QgsDataItem.Populated)
        my_projects.refresh()
        sip.transferto(my_projects, self)
        items.append(my_projects)

        shared_projects = MerginGroupItem(self, "Shared with me", "shared", "users.svg", 2, self.plugin)
        shared_projects.setState(QgsDataItem.Populated)
        shared_projects.refresh()
        sip.transferto(shared_projects, self)
        items.append(shared_projects)

        return items


class MerginRootItem(MerginRootItemBase):
    def __init__(self, plugin=None):
        MerginRootItemBase.__init__(self, plugin)

    def createChildren(self):
        if self.error or self.mc is None:
            self.error = self.error if self.error else "Not configured!"
            error_item = QgsErrorItem(self, self.error, "Mergin/error")
            error_item.setIcon(QIcon(icon_path("alert-triangle.svg")))
            sip.transferto(error_item, self)
            return [error_item]

        items = []
        my_projects = MerginGroupItem(self, "My projects", "created", "user.svg", 1, self.plugin)
        my_projects.setState(QgsDataItem.Populated)
        my_projects.refresh()
        sip.transferto(my_projects, self)
        items.append(my_projects)

        shared_projects = MerginGroupItem(self, "Shared with me", "shared", "users.svg", 2, self.plugin)
        shared_projects.setState(QgsDataItem.Populated)
        shared_projects.refresh()
        sip.transferto(shared_projects, self)
        items.append(shared_projects)

        return items


class MerginGroupItem(QgsDataCollectionItem):
    """Mergin group data item. Contains filtered list of Mergin Maps projects."""

    def __init__(self, parent, grp_name, grp_filter, icon, order, plugin):
        QgsDataCollectionItem.__init__(self, parent, grp_name, "/Mergin" + grp_name)
        self.filter = grp_filter
        self.setIcon(QIcon(icon_path(icon)))
        self.setSortKey(order)
        self.plugin = plugin
        self.project_manager = plugin.manager
        self.projects = []
        self.group_name = grp_name
        self.total_projects_count = None
        self.fetch_more_item = None

    def fetch_projects(self, page=1, per_page=PROJS_PER_PAGE):
        """Get paginated projects list from Mergin Maps service. If anything goes wrong, return an error item."""
        if self.project_manager is None:
            error_item = QgsErrorItem(self, "Failed to log in. Please check the configuration", "/Mergin/error")
            sip.transferto(error_item, self)
            return [error_item]
        try:
            resp = self.project_manager.mc.paginated_projects_list(
                flag=self.filter, page=page, per_page=per_page, order_params="namespace_asc,name_asc"
            )
            self.projects += resp["projects"]
            self.total_projects_count = int(resp["count"]) if is_number(resp["count"]) else 0
        except URLError:
            error_item = QgsErrorItem(self, "Failed to get projects from server", "/Mergin/error")
            sip.transferto(error_item, self)
            return [error_item]
        except Exception as err:
            error_item = QgsErrorItem(self, "Error: {}".format(str(err)), "/Mergin/error")
            sip.transferto(error_item, self)
            return [error_item]
        return None

    def createChildren(self):
        if not self.projects:
            error = self.fetch_projects()
            if error is not None:
                return error
        items = []
        for project in self.projects:
            project_name = posixpath.join(project["namespace"], project["name"])  # posix path for server API calls
            local_proj_path = mergin_project_local_path(project_name)
            if local_proj_path is None or not os.path.exists(local_proj_path):
                item = MerginRemoteProjectItem(self, project, self.project_manager)
                item.setState(QgsDataItem.Populated)  # make it non-expandable
            else:
                item = MerginLocalProjectItem(self, project, self.project_manager)
            sip.transferto(item, self)
            items.append(item)
        self.set_fetch_more_item()
        if self.fetch_more_item is not None:
            items.append(self.fetch_more_item)
        return items

    def set_fetch_more_item(self):
        """Check if there are more projects to be fetched from Mergin service and set the fetch-more item."""
        if self.fetch_more_item is not None:
            try:
                self.removeChildItem(self.fetch_more_item)
            except RuntimeError:
                pass
            self.fetch_more_item = None
        fetched_count = len(self.projects)
        if fetched_count < self.total_projects_count:
            self.fetch_more_item = FetchMoreItem(self)
            self.fetch_more_item.setState(QgsDataItem.Populated)
            sip.transferto(self.fetch_more_item, self)
        group_name = f"{self.group_name} ({self.total_projects_count})"
        self.setName(group_name)

    def fetch_more(self):
        """Fetch another page of projects and add them to the group item."""
        if self.fetch_more_item is None:
            QMessageBox.information(None, "Fetch Mergin Maps Projects", "All projects already listed.")
            return
        page_to_get = floor(self.rowCount() / PROJS_PER_PAGE) + 1
        dummy = self.fetch_projects(page=page_to_get)
        self.refresh()

    def reload(self):
        self.projects = []
        self.refresh()

    def actions(self, parent):
        action_refresh = QAction(QIcon(icon_path("repeat.svg")), "Reload", parent)
        action_refresh.triggered.connect(self.reload)
        actions = [action_refresh]
        if self.fetch_more_item is not None:
            action_fetch_more = QAction(QIcon(icon_path("dots.svg")), "Fetch more", parent)
            action_fetch_more.triggered.connect(self.fetch_more)
            actions.append(action_fetch_more)
        if self.name().startswith("My projects"):
            action_create = QAction(QIcon(icon_path("square-plus.svg")), "Create new project", parent)
            action_create.triggered.connect(self.plugin.create_new_project)
            actions.append(action_create)
        return actions


class MerginLocalProjectItem(QgsDirectoryItem):
    """Data item to represent a local Mergin Maps project."""

    def __init__(self, parent, project, project_manager):
        self.project_name = posixpath.join(project["namespace"], project["name"])  # posix path for server API calls
        self.path = mergin_project_local_path(self.project_name)
        QgsDirectoryItem.__init__(self, parent, self.project_name, self.path, "/Mergin/" + self.project_name)
        self.setSortKey(f"0 {self.name()}")
        self.project = project
        self.project_manager = project_manager
        if self.project_manager is not None:
            self.mc = self.project_manager.mc
        else:
            self.mc = None

    def open_project(self):
        self.project_manager.open_project(self.path)

    def sync_project(self):
        if not self.path:
            return
        self.project_manager.project_status(self.path)

    def _reload_project(self):
        """This will forcefully reload the QGIS project because the project (or its data) may have changed"""
        qgis_files = find_qgis_files(self.path)
        if QgsProject.instance().fileName() in qgis_files:
            iface.addProject(QgsProject.instance().fileName())

    def remove_local_project(self):
        if not self.path:
            return
        cur_proj = QgsProject.instance()
        cur_proj_path = cur_proj.absolutePath()
        msg = (
            "Your local changes will be lost. Make sure your project is synchronised with server. \n\n"
            "Do you want to proceed?".format(self.project_name)
        )
        btn_reply = QMessageBox.question(
            None, "Remove local project", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if btn_reply == QMessageBox.No:
            return

        if os.path.exists(self.path):
            try:
                if same_dir(cur_proj_path, self.path):
                    msg = (
                        "The project is currently open. It will get cleared if you proceed.\n\n"
                        "Proceed anyway?".format(self.project_name)
                    )
                    btn_reply = QMessageBox.question(
                        None, "Remove local project", msg, QMessageBox.No | QMessageBox.No, QMessageBox.Yes
                    )
                    if btn_reply == QMessageBox.No:
                        return

                    cur_proj.clear()
                    # clearing project does not trigger toggling toolbar buttons state
                    # change, so we need to fire the singnal manually
                    iface.newProjectCreated.emit()
                    registry = QgsProviderRegistry.instance()
                    registry.setLibraryDirectory(registry.libraryDirectory())

                # remove logging file handler
                mp = MerginProject(self.path)
                log_file_handler = mp.log.handlers[0]
                log_file_handler.close()
                mp.log.removeHandler(log_file_handler)
                del mp

                # as releasing lock on previously open files takes some time
                # we have to wait a bit before removing them, otherwise rmtree
                # will fail and removal of the local rpoject will fail as well
                QTimer.singleShot(250, lambda: shutil.rmtree(self.path))
            except PermissionError as e:
                QgsApplication.messageLog().logMessage(f"Mergin Maps plugin: {str(e)}")
                msg = (
                    f"Failed to delete your project {self.project_name} because it is open.\n"
                    "You might need to close project or QGIS to remove its files."
                )
                QMessageBox.critical(None, "Project delete", msg, QMessageBox.Close)
                return

        settings = QSettings()
        settings.remove(f"Mergin/localProjects/{self.project_name}")
        self.parent().reload()

    def submit_logs(self):
        if not self.path:
            return
        self.project_manager.submit_logs(self.path)

    def clone_remote_project(self):
        user_info = self.mc.user_info()
        dlg = CloneProjectDialog(username=user_info["username"], user_organisations=user_info.get("organisations", []))
        if not dlg.exec_():
            return  # cancelled
        try:
            self.mc.clone_project(self.project_name, dlg.project_name, dlg.project_namespace)
            msg = "Mergin Maps project cloned successfully."
            QMessageBox.information(None, "Clone project", msg, QMessageBox.Close)
            self.parent().reload()
        except (URLError, ClientError) as e:
            msg = "Failed to clone project {}:\n\n{}".format(self.project_name, str(e))
            QMessageBox.critical(None, "Clone project", msg, QMessageBox.Close)
        except LoginError as e:
            login_error_message(e)

    def actions(self, parent):
        action_remove_local = QAction(QIcon(icon_path("trash.svg")), "Remove locally", parent)
        action_remove_local.triggered.connect(self.remove_local_project)

        action_open_project = QAction("Open QGIS project", parent)
        action_open_project.triggered.connect(self.open_project)

        action_sync_project = QAction(QIcon(icon_path("refresh.svg")), "Synchronize", parent)
        action_sync_project.triggered.connect(self.sync_project)

        action_clone_remote = QAction(QIcon(icon_path("copy.svg")), "Clone", parent)
        action_clone_remote.triggered.connect(self.clone_remote_project)

        action_diagnostic_log = QAction(QIcon(icon_path("first-aid-kit.svg")), "Diagnostic log", parent)
        action_diagnostic_log.triggered.connect(self.submit_logs)

        actions = [
            action_open_project,
            action_sync_project,
            action_clone_remote,
            action_remove_local,
            action_diagnostic_log,
        ]
        return actions


class MerginRemoteProjectItem(QgsDataItem):
    """Data item to represent a remote Mergin Maps project."""

    def __init__(self, parent, project, project_manager):
        self.project = project
        self.project_name = posixpath.join(
            project["namespace"], project["name"]
        )  # we need posix path for server API calls
        QgsDataItem.__init__(self, QgsDataItem.Collection, parent, self.project_name, "/Mergin/" + self.project_name)
        self.path = None
        self.setSortKey(f"1 {self.name()}")
        self.setIcon(QIcon(icon_path("cloud.svg")))
        self.project_manager = project_manager
        if self.project_manager is not None:
            self.mc = self.project_manager.mc
        else:
            self.mc = None

    def download(self):
        settings = QSettings()
        last_parent_dir = settings.value("Mergin/lastUsedDownloadDir", str(Path.home()))
        parent_dir = QFileDialog.getExistingDirectory(None, "Open Directory", last_parent_dir, QFileDialog.ShowDirsOnly)
        if not parent_dir:
            return
        settings.setValue("Mergin/lastUsedDownloadDir", parent_dir)
        target_dir = os.path.abspath(os.path.join(parent_dir, self.project["name"]))
        if os.path.exists(target_dir):
            QMessageBox.warning(
                None,
                "Download Project",
                "The target directory already exists:\n" + target_dir + "\n\nPlease select a different directory.",
            )
            return

        dlg = SyncDialog()
        dlg.download_start(self.mc, target_dir, self.project_name)
        dlg.exec_()  # blocks until completion / failure / cancellation
        if dlg.exception:
            if isinstance(dlg.exception, (URLError, ValueError)):
                QgsApplication.messageLog().logMessage("Mergin Maps plugin: " + str(dlg.exception))
                msg = (
                    "Failed to download your project {}.\n"
                    "Please make sure your Mergin Maps settings are correct".format(self.project_name)
                )
                QMessageBox.critical(None, "Project download", msg, QMessageBox.Close)
            elif isinstance(dlg.exception, LoginError):
                login_error_message(dlg.exception)
            else:
                unhandled_exception_message(
                    dlg.exception_details(),
                    "Project download",
                    f"Failed to download project {self.project_name} due to an unhandled exception.",
                )
            return
        if not dlg.is_complete:
            return  # either it has been cancelled or an error has been thrown

        settings.setValue("Mergin/localProjects/{}/path".format(self.project_name), target_dir)
        self.path = target_dir
        msg = "Your project {} has been successfully downloaded. " "Do you want to open project file?".format(
            self.project_name
        )
        btn_reply = QMessageBox.question(
            None, "Project download", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if btn_reply == QMessageBox.Yes:
            self.open_project()
        self.parent().reload()

    def open_project(self):
        self.project_manager.open_project(self.path)

    def clone_remote_project(self):
        user_info = self.mc.user_info()
        dlg = CloneProjectDialog(username=user_info["username"], user_organisations=user_info.get("organisations", []))
        if not dlg.exec_():
            return  # cancelled
        try:
            self.mc.clone_project(self.project_name, dlg.project_name, dlg.project_namespace)
        except (URLError, ClientError) as e:
            msg = "Failed to clone project {}:\n\n{}".format(self.project_name, str(e))
            QMessageBox.critical(None, "Clone project", msg, QMessageBox.Close)
            return
        except LoginError as e:
            login_error_message(e)
            return
        msg = "Mergin Maps project cloned successfully."
        QMessageBox.information(None, "Clone project", msg, QMessageBox.Close)
        self.parent().reload()
        # we also need to reload My projects group as the cloned project could appear there
        group_items = self.project_manager.get_mergin_browser_groups()
        if "My projects" in group_items:
            group_items["My projects"].reload()

    def remove_remote_project(self):
        msg = "Do you really want to remove project {} from server?".format(self.project_name)
        btn_reply = QMessageBox.question(None, "Remove project", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if btn_reply == QMessageBox.No:
            return

        try:
            self.mc.delete_project(self.project_name)
            msg = "Mergin Maps project removed successfully."
            QMessageBox.information(None, "Remove project", msg, QMessageBox.Close)
            self.parent().reload()
        except (URLError, ClientError) as e:
            msg = "Failed to remove project {}:\n\n{}".format(self.project_name, str(e))
            QMessageBox.critical(None, "Remove project", msg, QMessageBox.Close)
        except LoginError as e:
            login_error_message(e)

    def actions(self, parent):
        action_download = QAction(QIcon(icon_path("cloud-download.svg")), "Download", parent)
        action_download.triggered.connect(self.download)

        action_clone_remote = QAction(QIcon(icon_path("copy.svg")), "Clone", parent)
        action_clone_remote.triggered.connect(self.clone_remote_project)

        action_remove_remote = QAction(QIcon(icon_path("trash.svg")), "Remove from server", parent)
        action_remove_remote.triggered.connect(self.remove_remote_project)

        actions = [action_download, action_clone_remote]
        if self.project["permissions"]["delete"]:
            actions.append(action_remove_remote)
        return actions


class FetchMoreItem(QgsDataItem):
    """Data item to represent an action to fetch more projects from paginated endpoint."""

    def __init__(self, parent):
        self.parent = parent
        QgsDataItem.__init__(self, QgsDataItem.Collection, parent, "Double-click for more...", "")
        self.setIcon(QIcon(icon_path("dots.svg")))
        self.setSortKey("2")  # the item should appear at the bottom of the list

    def handleDoubleClick(self):
        self.parent.fetch_more()
        return True

