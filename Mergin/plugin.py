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

MERGIN_CLIENT_LOG = os.path.join(QgsApplication.qgisSettingsDirPath(), "mergin-client-log.txt")
os.environ["MERGIN_CLIENT_LOG"] = MERGIN_CLIENT_LOG


class MerginPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.data_item_provider = None
        self.actions = []
        self.actions_always_on = []
        self.menu = "Mergin Maps"
        self.mergin_proj_dir = None
        self.mc = None
        self.manager = None
        self.provider = MerginProvider()
        self.toolbar = self.iface.addToolBar("Mergin Maps Toolbar")
        self.toolbar.setToolTip("Mergin Maps Toolbar")
        self.toolbar.setObjectName("MerginMapsToolbar")

        self.iface.projectRead.connect(self.on_qgis_project_changed)
        self.iface.newProjectCreated.connect(self.on_qgis_project_changed)

        settings = QSettings()
        QgsExpressionContextUtils.setGlobalVariable("mergin_username", settings.value("Mergin/username", ""))
        QgsExpressionContextUtils.setGlobalVariable("mergin_url", settings.value("Mergin/server", ""))

    def initProcessing(self):
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        # This is a quick fix for a bad crasher for users that have set up master password for their
        # storage of authentication configurations. What would happen is that in a worker thread,
        # QGIS browser model would start populating Mergin data items which would want to query Mergin
        # server and thus request auth info - but as this would be done in a background thread,
        # things will get horribly wrong when QGIS tries to display GUI and the app would crash.
        # Triggering auth request to QGIS auth framework already at this point will make sure that
        # the dialog asking for master password is started from the main thread -> no crash.
        get_mergin_auth()

        self.initProcessing()

        self.create_manager()

        self.add_action(
            icon_path("mm_icon_positive_no_padding.svg"),
            text="Mergin Maps",
            callback=self.open_configured_url,
            add_to_menu=True,
            add_to_toolbar=self.toolbar,
        )
        self.add_action(
            "settings.svg",
            text="Configure Mergin Maps Plugin",
            callback=self.configure,
            add_to_menu=True,
            add_to_toolbar=self.toolbar,
        )
        self.add_action(
            "square-plus.svg",
            text="Create Mergin Maps Project",
            callback=self.create_new_project,
            add_to_menu=False,
            add_to_toolbar=self.toolbar,
            enabled=False,
            always_on=False,
        )
        self.add_action(
            "refresh.svg",
            text="Synchronise Mergin Maps Project",
            callback=self.current_project_sync,
            add_to_menu=False,
            add_to_toolbar=self.toolbar,
            enabled=False,
            always_on=False,
        )

        self.enable_toolbar_actions()

        self.post_login()

        self.data_item_provider = DataItemProvider(self)
        QgsApplication.instance().dataItemProviderRegistry().addProvider(self.data_item_provider)
        # related to https://github.com/MerginMaps/qgis-mergin-plugin/issues/3
        # if self.iface.browserModel().initialized():
        #     self.iface.browserModel().reload()

        # register custom mergin widget in project properties
        self.mergin_project_config_factory = MerginProjectConfigFactory()
        self.iface.registerProjectPropertiesWidgetFactory(self.mergin_project_config_factory)

        # add layer context menu action for checking local changes
        self.action_show_changes = QAction("Show Local Changes", self.iface.mainWindow())
        self.action_show_changes.setIcon(QIcon(icon_path("file-diff.svg")))
        self.iface.addCustomActionForLayerType(self.action_show_changes, "", QgsMapLayer.VectorLayer, True)
        self.action_show_changes.triggered.connect(self.view_local_changes)

    def add_action(
        self,
        icon_name,
        callback=None,
        text="",
        enabled=True,
        add_to_menu=False,
        add_to_toolbar=None,
        status_tip=None,
        whats_this=None,
        checkable=False,
        checked=False,
        always_on=True,
    ):

        icon = QIcon(icon_path(icon_name))
        action = QAction(icon, text, self.iface.mainWindow())
        action.triggered.connect(callback)
        action.setCheckable(checkable)
        action.setChecked(checked)
        action.setEnabled(enabled)

        if status_tip is not None:
            action.setStatusTip(status_tip)
        if whats_this is not None:
            action.setWhatsThis(whats_this)
        if add_to_toolbar is not None:
            add_to_toolbar.addAction(action)
        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)
        if always_on:
            self.actions_always_on.append(text)
        return action

    def create_manager(self):
        """Create Mergin Maps projects manager."""
        error = ""
        try:
            if self.mc is None:
                self.mc = create_mergin_client()
            self.manager = MerginProjectsManager(self.mc)
        except (URLError, ClientError, LoginError):
            error = "Plugin not configured or \nQGIS master password not set up"
        except Exception as err:
            error = "Error: {}".format(str(err))
        if error:
            self.mc = None
            self.manager = None
        if self.has_browser_item():
            self.data_item_provider.root_item.update_client_and_manager(mc=self.mc, manager=self.manager, err=error)

    def has_browser_item(self):
        """Check if the Mergin Maps provider Browser item exists and has the root item defined."""
        if self.data_item_provider is not None:
            if self.data_item_provider.root_item is not None:
                return True
        return False

    def on_config_changed(self):
        """Called when plugin config (connection settings) were changed."""
        self.create_manager()
        self.enable_toolbar_actions()
        self.post_login()

    def open_configured_url(self):
        """Opens configured Mergin Maps server url in default browser"""
        if self.mc is None:
            url = QUrl("https://merginmaps.com")
        else:
            url = QUrl(self.mc.url)

        QDesktopServices.openUrl(url)

    def enable_toolbar_actions(self, enable=None):
        """Check current project and set Mergin Maps Toolbar icons enabled accordingly."""
        if enable is None:
            enable = mergin_project_local_path() is not None
        if self.manager is None:
            enable = False
        for action in self.toolbar.actions():
            if action.text() in self.actions_always_on:
                action.setEnabled(True)
            elif action.text() == "Create Mergin Maps Project":
                action.setEnabled(self.mc is not None and self.manager is not None)
            else:
                action.setEnabled(enable)

    def show_browser_panel(self):
        """Check if QGIS Browser panel is open. If not, ask and eventually make it visible to users."""
        browser = [w for w in self.iface.mainWindow().findChildren(QDockWidget) if w.objectName() == "Browser"][0]
        q = "QGIS Browser panel is currently off. The panel is used for Mergin Maps projects management.\n"
        q += "Would you like to open it and see your Mergin projects?"
        if not browser.isVisible():
            res = QMessageBox.question(None, "Mergin Maps - QGIS Browser Panel", q)
            if res == QMessageBox.Yes:
                self.iface.addDockWidget(Qt.LeftDockWidgetArea, browser)

    def configure(self):
        """Open plugin configuration dialog."""
        dlg = ConfigurationDialog()
        if dlg.exec_():
            self.mc = dlg.writeSettings()
            self.on_config_changed()
            self.show_browser_panel()

    def post_login(self):
        """Groups actions that needs to be done when auth information changes"""
        if not self.mc:
            return

        settings = QSettings()

        # check action required flag
        service_response = self.mc.user_service()

        if service_response and type(service_response) is dict:
            requires_action = service_response.get("action_required", False)

            if requires_action:
                iface.messageBar().pushMessage(
                    "Mergin Maps",
                    "Your attention is required.&nbsp;Please visit the "
                    f"<a href='{self.mc.url}/dashboard?utm_source=plugin&utm_medium=attention-required'>"
                    "Mergin dashboard</a>",
                    level=Qgis.Critical,
                    duration=0,
                )

    def create_new_project(self):
        """Open new Mergin Maps project creation dialog."""
        check_result = unsaved_project_check()
        if check_result == UnsavedChangesStrategy.HasUnsavedChanges:
            return
        if not self.manager:
            QMessageBox.warning(None, "Create Mergin Maps Project", "Plugin not configured!")
            return

        user_info = self.mc.user_info()
        wizard = NewMerginProjectWizard(
            self.manager, username=user_info["username"], user_organisations=user_info.get("organisations", [])
        )
        if not wizard.exec_():
            return  # cancelled
        if self.has_browser_item():
            # make sure the item has the link between remote and local project we have just added
            self.data_item_provider.root_item.depopulate()

    def current_project_sync(self):
        """Synchronise current Mergin Maps project."""
        self.manager.project_status(self.mergin_proj_dir)

    def on_qgis_project_changed(self):
        """
        Called when QGIS project is created or (re)loaded. Sets QGIS project related Mergin Maps variables.
        If a loaded project is not a Mergin Maps project, there are no Mergin variables by default.
        If a loaded project is invalid - doesnt have metadata, Mergin variables are removed.
        """
        self.enable_toolbar_actions(enable=False)
        self.mergin_proj_dir = mergin_project_local_path()
        if self.mergin_proj_dir is not None:
            self.enable_toolbar_actions()

    def unload(self):
        # Disconnect Mergin related signals
        self.iface.projectRead.disconnect(self.on_qgis_project_changed)
        self.iface.newProjectCreated.disconnect(self.on_qgis_project_changed)

        remove_project_variables()
        QgsExpressionContextUtils.removeGlobalVariable("mergin_username")
        QgsExpressionContextUtils.removeGlobalVariable("mergin_url")
        QgsApplication.instance().dataItemProviderRegistry().removeProvider(self.data_item_provider)
        self.data_item_provider = None
        # this is crashing qgis on exit
        # self.iface.browserModel().reload()

        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
        del self.toolbar

        self.iface.removeCustomActionForLayerType(self.action_show_changes)

        self.iface.unregisterProjectPropertiesWidgetFactory(self.mergin_project_config_factory)
        QgsApplication.processingRegistry().removeProvider(self.provider)

    def view_local_changes(self):
        project_path = QgsProject.instance().homePath()
        if not project_path:
            iface.messageBar().pushMessage(
                "Mergin", "Project is not saved, can not compute local changes", Qgis.Warning
            )
            return

        if not check_mergin_subdirs(project_path):
            iface.messageBar().pushMessage("Mergin", "Current project is not a Mergin project.", Qgis.Warning)
            return

        check_result = unsaved_project_check()
        if check_result == UnsavedChangesStrategy.HasUnsavedChanges:
            return

        mp = MerginProject(QgsProject.instance().homePath())
        push_changes = mp.get_push_changes()
        push_changes_summary = mp.get_list_of_push_changes(push_changes)
        if not push_changes_summary:
            iface.messageBar().pushMessage("Mergin", "No changes found in the project layers.", Qgis.Info)
            return

        selected_layers = self.iface.layerTreeView().selectedLayersRecursive()
        layer_name = None
        for layer in selected_layers:
            if layer.type() != QgsMapLayer.VectorLayer:
                continue

            if layer.dataProvider().storageType() == "GPKG":
                layer_name = layer.name()
                break

        dlg_diff_viewer = DiffViewerDialog()
        if check_result == UnsavedChangesStrategy.HasUnsavedChangesButIgnore:
            dlg_diff_viewer.show_unsaved_changes_warning()
        if layer_name:
            for i, layer in enumerate(dlg_diff_viewer.diff_layers):
                if layer_name in layer.name():
                    dlg_diff_viewer.tab_bar.setCurrentIndex(i)
                    break
        dlg_diff_viewer.show()
        dlg_diff_viewer.exec_()


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


class MerginLocalProjectItem(QgsDirectoryItem):
    """Data item to represent a local Mergin Maps project."""

    def __init__(self, parent, project, project_manager):
        self.project_name = posixpath.join(project["namespace"], project["name"])  # posix path for server API calls
        self.path = mergin_project_local_path(self.project_name)
        QgsDirectoryItem.__init__(self, parent, self.project_name, self.path, "/Mergin/" + self.project_name)
        self.setSortKey(f"1 {self.name()}")
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


class MerginRootItem(QgsDataCollectionItem):
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

        all_projects = MerginGroupItem(self, "Explore", None, "list.svg", 3, self.plugin)
        all_projects.setState(QgsDataItem.Populated)
        all_projects.refresh()
        sip.transferto(all_projects, self)
        items.append(all_projects)

        return items

    def actions(self, parent):
        action_configure = QAction(QIcon(icon_path("settings.svg")), "Configure", parent)
        action_configure.triggered.connect(self.plugin.configure)

        action_create = QAction(QIcon(icon_path("square-plus.svg")), "Create new project", parent)
        action_create.triggered.connect(self.plugin.create_new_project)
        actions = [action_configure]
        if self.mc:
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
            ri = MerginRootItem(self.plugin)
            sip.transferto(ri, None)
            self.root_item = ri
            return ri
        else:
            return None
