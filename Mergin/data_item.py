# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited

from math import floor

try:
    import sip
except ImportError:
    from PyQt6 import sip
import os
import shutil
import logging
import posixpath
from qgis.PyQt.QtCore import pyqtSignal, QTimer, QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QDialog
from qgis.core import (
    QgsApplication,
    QgsDataCollectionItem,
    QgsDataItem,
    QgsDataItemProvider,
    QgsDataProvider,
    QgsDirectoryItem,
    QgsErrorItem,
    QgsProject,
    QgsProviderRegistry,
)
from qgis.utils import iface
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from urllib.error import URLError

from .clone_project_dialog import CloneProjectDialog
from .remove_project_dialog import RemoveProjectDialog
from .utils import (
    ServerType,
    ClientError,
    LoginError,
    icon_path,
    mm_symbol_path,
    is_number,
    login_error_message,
    mergin_project_local_path,
    PROJS_PER_PAGE,
    same_dir,
    get_local_mergin_projects_info,
)
from .utils_auth import AuthTokenExpiredError
from .mergin.merginproject import MerginProject


class MerginRemoteProjectItem(QgsDataItem):
    """Data item to represent a remote Mergin Maps project."""

    def __init__(self, parent, project, project_manager, plugin):
        self.project = project
        self.plugin = plugin
        self.project_name = posixpath.join(
            project["namespace"], project["name"]
        )  # we need posix path for server API calls
        display_name = project["name"]
        QgsDataItem.__init__(self, QgsDataItem.Collection, parent, display_name, "/Mergin/" + self.project_name)
        self.path = None
        self.setSortKey(f"1 {self.name()}")
        self.setIcon(QIcon(icon_path("cloud.svg")))
        self.project_manager = project_manager
        if self.project_manager is not None:
            self.mc = self.project_manager.mc
        else:
            self.mc = None

    def download(self):
        self.project_manager.download_project(self.project)
        return

    def open_project(self):
        self.project_manager.open_project(self.path)

    def clone_remote_project(self):
        user_info = self.mc.user_info()

        dlg = CloneProjectDialog(user_info=user_info, default_workspace=self.project["namespace"])
        if not dlg.exec():
            return  # cancelled
        try:
            self.mc.clone_project(self.project_name, dlg.project_name, dlg.project_namespace)
        except (URLError, ClientError) as e:
            msg = "Failed to clone project {}:\n\n{}".format(self.project_name, str(e))
            QMessageBox.critical(None, "Clone project", msg, QMessageBox.StandardButton.Close)
            return
        except AuthTokenExpiredError:
            self.plugin.auth_token_expired()
            return
        except LoginError as e:
            login_error_message(e)
            return
        msg = "Mergin Maps project cloned successfully."
        QMessageBox.information(None, "Clone project", msg, QMessageBox.StandardButton.Close)
        self.parent().reload()

    def remove_remote_project(self):
        dlg = RemoveProjectDialog(self.project["namespace"], self.project["name"])
        if dlg.exec() == QDialog.DialogCode.Rejected:
            return

        try:
            self.mc.delete_project(self.project_name)
            msg = "Mergin Maps project removed successfully."
            QMessageBox.information(None, "Remove project", msg, QMessageBox.StandardButton.Close)
            self.parent().reload()
        except (URLError, ClientError) as e:
            msg = "Failed to remove project {}:\n\n{}".format(self.project_name, str(e))
            QMessageBox.critical(None, "Remove project", msg, QMessageBox.StandardButton.Close)
        except AuthTokenExpiredError:
            self.plugin.auth_token_expired()
            return
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


class MerginLocalProjectItem(QgsDirectoryItem):
    """Data item to represent a local Mergin Maps project."""

    def __init__(self, parent, project, project_manager, plugin):
        self.plugin = plugin
        self.project_name = posixpath.join(project["namespace"], project["name"])  # posix path for server API calls
        self.path = mergin_project_local_path(self.project_name)
        display_name = project["name"]
        QgsDirectoryItem.__init__(self, parent, display_name, self.path, "/Mergin/" + self.project_name)
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

    def _close_file_handlers_under(self, path: str):
        """Close any logging.FileHandler that writes inside `path` (project dir).
        This releases Windows file locks (e.g. .mergin/client-log.txt) before rmtree.
        """
        path = os.path.abspath(path)
        # Iterate all known loggers in this Python process
        for logger in list(logging.Logger.manager.loggerDict.values()):
            if isinstance(logger, logging.Logger):
                for h in list(logger.handlers):
                    # Only FileHandlers have baseFilename; skip others (Stream, etc.)
                    bf = getattr(h, "baseFilename", None)
                    if bf:
                        try:
                            # Close handlers whose files live under the project path
                            if os.path.commonpath([os.path.abspath(bf), path]) == path:
                                h.flush()
                                h.close()
                                logger.removeHandler(h)

                        except (ValueError, OSError, RuntimeError):
                            pass
        # Ensure logging subsystem finishes cleanup
        try:
            logging.shutdown()
        except (OSError, ValueError, RuntimeError):
            pass

    def _delete_or_retry(self, path: str):
        """Delete project directory (no rename, no retries)."""
        try:
            shutil.rmtree(path)
        except PermissionError as e:
            # Optional: user-facing message when files are still locked
            QMessageBox.critical(
                None, "Project delete", f"Some files are still in use.\n\n{e}\n\nClose the project/QGIS and try again."
            )

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
            None,
            "Remove local project",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if btn_reply == QMessageBox.StandardButton.No:
            return

        if os.path.exists(self.path):
            try:
                if same_dir(cur_proj_path, self.path):
                    msg = (
                        "The project is currently open. It will get cleared if you proceed.\n\n"
                        "Proceed anyway?".format(self.project_name)
                    )
                    btn_reply = QMessageBox.question(
                        None,
                        "Remove local project",
                        msg,
                        QMessageBox.StandardButton.No | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes,
                    )
                    if btn_reply == QMessageBox.StandardButton.No:
                        return

                    cur_proj.clear()
                    # clearing project does not trigger toggling toolbar buttons state
                    # change, so we need to fire the singnal manually
                    iface.newProjectCreated.emit()
                    registry = QgsProviderRegistry.instance()
                    registry.setLibraryDirectory(registry.libraryDirectory())

                # Close all file handlers under this project so Windows releases .mergin/client-log.txt before rmtree
                self._close_file_handlers_under(self.path)

                # Delay deletion by 400 ms so file handlers can fully close
                # run delete via the Qt event loop
                QTimer.singleShot(400, lambda: self._delete_or_retry(self.path))

            except PermissionError as e:
                QgsApplication.messageLog().logMessage(f"Mergin Maps plugin: {str(e)}")
                msg = (
                    f"Failed to delete your project {self.project_name} because it is open.\n"
                    "You might need to close project or QGIS to remove its files."
                )
                QMessageBox.critical(None, "Project delete", msg, QMessageBox.StandardButton.Close)
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

        dlg = CloneProjectDialog(user_info=user_info, default_workspace=self.project["namespace"])

        if not dlg.exec():
            return  # cancelled
        try:
            self.mc.clone_project(self.project_name, dlg.project_name, dlg.project_namespace)
            msg = "Mergin Maps project cloned successfully."
            QMessageBox.information(None, "Clone project", msg, QMessageBox.StandardButton.Close)
            self.parent().reload()
        except (URLError, ClientError) as e:
            msg = "Failed to clone project {}:\n\n{}".format(self.project_name, str(e))
            QMessageBox.critical(None, "Clone project", msg, QMessageBox.StandardButton.Close)
        except AuthTokenExpiredError:
            self.plugin.auth_token_expired()
            return
        except LoginError as e:
            login_error_message(e)

    def actions(self, parent):
        action_remove_local = QAction(QIcon(icon_path("trash.svg")), "Remove locally", parent)
        action_remove_local.triggered.connect(self.remove_local_project)

        action_open_project = QAction("Open QGIS project", parent)
        action_open_project.triggered.connect(self.open_project)

        action_sync_project = QAction(QIcon(icon_path("refresh.svg")), "Synchronise", parent)
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


class ErrorItem(QgsErrorItem):
    """Data item used to report errors with double-click support."""

    def __init__(self, parent, error, path, double_click_handler=None):
        QgsErrorItem.__init__(self, parent, error, path)
        self.parent = parent
        self.handler = double_click_handler
        self.setIcon(QIcon(icon_path("alert-triangle.svg")))

    def handleDoubleClick(self):
        if self.handler:
            self.handler()
            return True
        else:
            return False


class CreateNewProjectItem(QgsDataItem):
    """Data item to represent an action to create a new project."""

    def __init__(self, parent):
        self.parent = parent
        QgsDataItem.__init__(self, QgsDataItem.Collection, parent, "Create new project...", "")
        self.setIcon(QIcon(icon_path("square-plus.svg")))

    def handleDoubleClick(self):
        self.parent.new_project()
        return True


class MerginRootItem(QgsDataCollectionItem):
    """Mergin root data containing project groups item with configuration dialog."""

    local_project_removed = pyqtSignal()

    def __init__(
        self,
        parent=None,
        name="Mergin Maps",
        flag=None,
        order=None,
        plugin=None,
    ):
        providerKey = "Mergin Maps"
        if name != providerKey:
            providerKey = "/Mergin" + name
        QgsDataCollectionItem.__init__(self, parent, name, providerKey)
        self.setIcon(QIcon(mm_symbol_path()))
        self.setSortKey(order)
        self.plugin = plugin
        self.project_manager = plugin.manager
        self.mc = self.project_manager.mc if self.project_manager is not None else None
        self.error = ""
        self.wizard = None
        self.projects = []
        self.local_projects = []
        self.total_projects_count = None
        self.fetch_more_item = None
        self.create_new_project_item = None
        self.filter = flag
        self.base_name = self.name()
        self.updateName()

    def update_client_and_manager(self, mc=None, manager=None, err=None):
        """Update Mergin client and project manager - used when starting or after a config change."""
        self.mc = mc
        self.project_manager = manager
        self.error = err
        self.projects = []
        self.local_projects = []
        self.updateName()
        self.depopulate()

    def updateName(self):
        name = self.base_name
        try:
            name = f"{self.base_name} [{self.plugin.current_workspace['name']}]"
        except KeyError:
            # self.mc might not be set yet or there is no workspace
            pass
        self.setName(name)

    def createChildren(self):
        if self.error or self.mc is None:
            handler = None
            if not self.error:
                handler = self.configure
                self.error = "Double-click to configure…"
            error_item = ErrorItem(self, self.error, "Mergin/error", handler)
            error_item.setIcon(QIcon(icon_path("alert-triangle.svg")))
            sip.transferto(error_item, self)
            return [error_item]

        return self.createChildrenProjects()

    def createChildrenProjects(self):
        if not self.projects:
            error = self.fetch_projects()
            if error is not None:
                return error
        if not self.local_projects:
            self.local_projects = [
                {"namespace": i[1], "name": i[2]}
                for i in get_local_mergin_projects_info(self.plugin.current_workspace["name"])
            ]
        items = []

        # build a set of (namespace, name) tuples for quick lookup
        local_keys = {(p["namespace"], p["name"]) for p in self.local_projects}
        # projects not present locally
        remote_only = [p for p in self.projects if (p["namespace"], p["name"]) not in local_keys]

        for project in self.local_projects:
            item = MerginLocalProjectItem(self, project, self.project_manager, self.plugin)
            sip.transferto(item, self)
            items.append(item)

        for project in remote_only:
            item = MerginRemoteProjectItem(self, project, self.project_manager, self.plugin)
            item.setState(QgsDataItem.Populated)  # make it non-expandable
            sip.transferto(item, self)
            items.append(item)
        self.set_fetch_more_item()
        if self.fetch_more_item is not None:
            items.append(self.fetch_more_item)
        if not items:
            self.create_new_project_item = CreateNewProjectItem(self)
            self.create_new_project_item.setState(QgsDataItem.Populated)
            sip.transferto(self.create_new_project_item, self)
            items.append(self.create_new_project_item)
        return items

    def fetch_projects(self, page=1, per_page=PROJS_PER_PAGE):
        """Get paginated projects list from Mergin Maps service. If anything goes wrong, return an error item."""
        if self.project_manager is None:
            error_item = QgsErrorItem(self, "Failed to log in. Please check the configuration", "/Mergin/error")
            sip.transferto(error_item, self)
            return [error_item]
        if not self.plugin.current_workspace:
            error_item = QgsErrorItem(self, "No workspace available", "/Mergin/error")
            sip.transferto(error_item, self)
            return [error_item]
        try:
            resp = self.project_manager.mc.paginated_projects_list(
                only_namespace=self.plugin.current_workspace.get("name", None),
                page=page,
                per_page=per_page,
                order_params="name_asc",
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

    def fetch_more(self):
        """Fetch another page of projects and add them to the group item."""
        if self.fetch_more_item is None:
            QMessageBox.information(None, "Fetch Mergin Maps Projects", "All projects already listed.")
            return
        page_to_get = floor(len(self.projects) / PROJS_PER_PAGE) + 1
        dummy = self.fetch_projects(page=page_to_get)
        self.refresh()

    def reload(self):
        if not self.plugin.current_workspace:
            self.plugin.choose_active_workspace()

        self.projects = []
        self.local_projects = [
            {"namespace": i[1], "name": i[2]}
            for i in get_local_mergin_projects_info(self.plugin.current_workspace["name"])
        ]
        self.refresh()

    def new_project(self):
        """Start the Create new project wizard"""
        self.plugin.create_new_project()

    def configure(self):
        self.plugin.configure()

    def actions(self, parent):
        action_configure = QAction(QIcon(icon_path("settings.svg")), "Configure", parent)
        action_configure.triggered.connect(self.plugin.configure)

        action_refresh = QAction(QIcon(icon_path("repeat.svg")), "Refresh", parent)
        action_refresh.triggered.connect(self.reload)

        action_create = QAction(QIcon(icon_path("square-plus.svg")), "Create new project", parent)
        action_create.triggered.connect(self.new_project)

        action_find = QAction(QIcon(icon_path("search.svg")), "Find project", parent)
        action_find.triggered.connect(self.plugin.find_project)

        action_switch = QAction(QIcon(icon_path("replace.svg")), "Switch workspace", parent)
        action_switch.triggered.connect(self.plugin.switch_workspace)

        action_explore = QAction(QIcon(icon_path("explore.svg")), "Explore public projects", parent)
        action_explore.triggered.connect(self.plugin.explore_public_projects)

        actions = [action_configure]
        if self.mc:
            server_type = self.mc.server_type()
            if server_type == ServerType.CE:
                actions.append(action_refresh)
                actions.append(action_create)
                actions.append(action_find)
                actions.append(action_explore)
            elif server_type in (ServerType.EE, ServerType.SAAS):
                actions.append(action_refresh)
                actions.append(action_create)
                actions.append(action_find)
                actions.append(action_switch)
                actions.append(action_explore)
        return actions


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
            ri = MerginRootItem(plugin=self.plugin)
            sip.transferto(ri, None)
            self.root_item = ri
            return ri
        else:
            return None
