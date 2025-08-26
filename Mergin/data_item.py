from math import floor

try:
    import sip
except ImportError:
    from PyQt6 import sip
import os
import shutil
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
)
from .utils_auth import AuthTokenExpiredError
from .mergin.merginproject import MerginProject

MERGIN_CLIENT_LOG = os.path.join(QgsApplication.qgisSettingsDirPath(), "mergin-client-log.txt")
os.environ["MERGIN_CLIENT_LOG"] = MERGIN_CLIENT_LOG


class MerginRemoteProjectItem(QgsDataItem):
    """Data item to represent a remote Mergin Maps project."""

    def __init__(self, parent, project, project_manager, plugin):
        self.project = project
        self.plugin = plugin
        self.project_name = posixpath.join(
            project["namespace"], project["name"]
        )  # we need posix path for server API calls
        display_name = project["name"]
        group_items = project_manager.get_mergin_browser_groups()
        if group_items.get("Shared with me") == parent:
            display_name = self.project_name
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent,
            display_name,
            "/Mergin/" + self.project_name,
        )
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
        # we also need to reload My projects group as the cloned project could appear there
        group_items = self.project_manager.get_mergin_browser_groups()
        if "My projects" in group_items:
            group_items["My projects"].reload()

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
        group_items = project_manager.get_mergin_browser_groups()
        if group_items.get("Shared with me") == parent:
            display_name = self.project_name
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
        self.updateName()
        self.depopulate()

    def updateName(self):
        name = self.base_name
        try:
            if self.mc.server_type() != ServerType.OLD and self.plugin.current_workspace.get("name", None):
                name = f"{self.base_name} [{self.plugin.current_workspace['name']}]"
        except AttributeError:
            # self.mc might not be set yet
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

        if self.mc.server_type() == ServerType.OLD:
            return self.createChildrenGroups()

        return self.createChildrenProjects()

    def createChildrenProjects(self):
        if not self.projects:
            error = self.fetch_projects()
            if error is not None:
                return error
        items = []
        for project in self.projects:
            project_name = posixpath.join(project["namespace"], project["name"])  # posix path for server API calls
            local_proj_path = mergin_project_local_path(project_name)
            if local_proj_path is None or not os.path.exists(local_proj_path):
                item = MerginRemoteProjectItem(self, project, self.project_manager, self.plugin)
                item.setState(QgsDataItem.Populated)  # make it non-expandable
            else:
                item = MerginLocalProjectItem(self, project, self.project_manager, self.plugin)
            sip.transferto(item, self)
            items.append(item)
        self.set_fetch_more_item()
        if self.fetch_more_item is not None:
            items.append(self.fetch_more_item)
        if not items and self.mc.server_type() != ServerType.OLD:
            self.create_new_project_item = CreateNewProjectItem(self)
            self.create_new_project_item.setState(QgsDataItem.Populated)
            sip.transferto(self.create_new_project_item, self)
            items.append(self.create_new_project_item)
        return items

    def createChildrenGroups(self):
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

    def fetch_projects(self, page=1, per_page=PROJS_PER_PAGE):
        """Get paginated projects list from Mergin Maps service. If anything goes wrong, return an error item."""
        if self.project_manager is None:
            error_item = QgsErrorItem(
                self,
                "Failed to log in. Please check the configuration",
                "/Mergin/error",
            )
            sip.transferto(error_item, self)
            return [error_item]
        if self.mc.server_type() != ServerType.OLD and not self.plugin.current_workspace:
            error_item = QgsErrorItem(self, "No workspace available", "/Mergin/error")
            sip.transferto(error_item, self)
            return [error_item]
        try:
            if self.mc.server_type() == ServerType.OLD:
                resp = self.project_manager.mc.paginated_projects_list(
                    flag=self.filter,
                    page=page,
                    per_page=per_page,
                    order_params="namespace_asc,name_asc",
                )
            else:
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
        if isinstance(self, MerginGroupItem):
            group_name = f"{self.base_name} ({self.total_projects_count})"
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
        if not self.plugin.current_workspace:
            self.plugin.choose_active_workspace()

        self.projects = []
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
            if server_type == ServerType.OLD:
                actions.append(action_create)
                actions.append(action_explore)
            elif server_type == ServerType.CE:
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


class MerginGroupItem(MerginRootItem):
    """Mergin group data item. Contains filtered list of Mergin Maps projects."""

    def __init__(self, parent, grp_name, grp_filter, icon, order, plugin):
        MerginRootItem.__init__(self, parent, grp_name, grp_filter, icon, order, plugin)

    def isMerginGroupItem(self):
        return True

    def createChildren(self):
        return self.createChildrenProjects()

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
            action_create.triggered.connect(self.new_project)
            actions.append(action_create)
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
