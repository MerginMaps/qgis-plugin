# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited
try:
    import sip
except ImportError:
    from PyQt6 import sip
import os
from functools import partial
from qgis.PyQt.QtCore import QUrl, QSettings, Qt
from qgis.PyQt.QtGui import QIcon, QDesktopServices
from qgis.core import (
    QgsApplication,
    QgsExpressionContextUtils,
    QgsProject,
    QgsMapLayer,
    Qgis,
)
from qgis.utils import iface
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QDockWidget
from urllib.error import URLError

from .configuration_dialog import ConfigurationDialog
from .workspace_selection_dialog import WorkspaceSelectionDialog
from .project_selection_dialog import (
    ProjectSelectionDialog,
    PublicProjectSelectionDialog,
)
from .data_item import DataItemProvider
from .create_project_wizard import NewMerginProjectWizard
from .diff_dialog import DiffViewerDialog
from .project_settings_widget import MerginProjectConfigFactory
from .projects_manager import MerginProjectsManager
from .configure_sync_wizard import DbSyncConfigWizard
from .version_viewer_dialog import VersionViewerDialog
from .utils import (
    ServerType,
    ClientError,
    LoginError,
    InvalidProject,
    check_mergin_subdirs,
    icon_path,
    mm_symbol_path,
    mergin_project_local_path,
    PROJS_PER_PAGE,
    remove_project_variables,
    set_qgis_project_mergin_variables,
    unsaved_project_check,
    UnsavedChangesStrategy,
)
from .utils_auth import (
    create_mergin_client,
    MissingAuthConfigError,
    AuthTokenExpiredError,
    set_qgsexpressionscontext,
    get_authcfg,
)

from .mergin.merginproject import MerginProject
from .processing.provider import MerginProvider
import processing

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
        # current_workspace is a dict with "name" and "id" keys, empty dict() if the server does not support workspaces
        self.current_workspace = dict()
        self.provider = MerginProvider()

        if self.iface is not None:
            self.toolbar = self.iface.addToolBar("Mergin Maps Toolbar")
            self.toolbar.setToolTip("Mergin Maps Toolbar")
            self.toolbar.setObjectName("MerginMapsToolbar")

            self.iface.projectRead.connect(self.on_qgis_project_changed)
            self.on_qgis_project_changed()
            self.iface.newProjectCreated.connect(self.on_qgis_project_changed)

        settings = QSettings()
        QgsExpressionContextUtils.setGlobalVariable("mergin_username", settings.value("Mergin/username", ""))
        QgsExpressionContextUtils.setGlobalVariable("mm_username", settings.value("Mergin/username", ""))
        QgsExpressionContextUtils.setGlobalVariable("mergin_url", settings.value("Mergin/server", ""))
        QgsExpressionContextUtils.setGlobalVariable("mm_url", settings.value("Mergin/server", ""))
        QgsExpressionContextUtils.setGlobalVariable("mergin_full_name", settings.value("Mergin/full_name", ""))
        QgsExpressionContextUtils.setGlobalVariable("mm_full_name", settings.value("Mergin/full_name", ""))
        QgsExpressionContextUtils.setGlobalVariable("mergin_user_email", settings.value("Mergin/user_email", ""))
        QgsExpressionContextUtils.setGlobalVariable("mm_user_email", settings.value("Mergin/user_email", ""))

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

        self.initProcessing()

        if self.iface is not None:
            self.add_action(
                mm_symbol_path(),
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
            self.action_db_sync_wizard = self.add_action(
                "database-cog.svg",
                text="Configure DB sync",
                callback=self.configure_db_sync,
                add_to_menu=True,
                add_to_toolbar=None,
            )
            self.add_action(
                "history.svg",
                text="Project History",
                callback=self.open_project_history_window,
                add_to_menu=False,
                add_to_toolbar=self.toolbar,
                enabled=False,
                always_on=False,
            )

            self.enable_toolbar_actions()

        self.data_item_provider = DataItemProvider(self)
        QgsApplication.instance().dataItemProviderRegistry().addProvider(self.data_item_provider)
        # related to https://github.com/MerginMaps/qgis-mergin-plugin/issues/3
        # if self.iface.browserModel().initialized():
        #     self.iface.browserModel().reload()

        # create manager based on status of QGIS
        # if main window is visible, we can create the manager immediately - QGIS is already initialized
        # if not, we need to wait for initializationCompleted signal so that QGIS is fully initialized
        if self.iface.mainWindow().isVisible():
            self.create_manager()
        else:
            self.iface.initializationCompleted.connect(self.create_manager)

        if self.iface is not None:
            # register custom mergin widget in project properties
            self.mergin_project_config_factory = MerginProjectConfigFactory()
            self.iface.registerProjectPropertiesWidgetFactory(self.mergin_project_config_factory)

            # add layer context menu action for checking local changes
            self.action_show_changes = QAction("Show Local Changes", self.iface.mainWindow())
            self.action_show_changes.setIcon(QIcon(icon_path("file-diff.svg")))
            self.iface.addCustomActionForLayerType(self.action_show_changes, "", QgsMapLayer.VectorLayer, True)
            self.action_show_changes.triggered.connect(self.view_local_changes)

            # add layer context menu action for downloading vector tiles
            self.action_export_mbtiles = QAction("Make available offline…", self.iface.mainWindow())
            self.action_export_mbtiles.setIcon(QIcon(icon_path("file-export.svg")))
            self.iface.addCustomActionForLayerType(self.action_export_mbtiles, "", QgsMapLayer.VectorTileLayer, False)
            self.action_export_mbtiles.triggered.connect(self.export_vector_tiles)

        QgsProject.instance().layersAdded.connect(self.add_context_menu_actions)

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
            if self.mc is None and get_authcfg():
                try:
                    self.mc = create_mergin_client()
                # if the client creation fails with AuthTokenExpiredError, we need relogin user - it should only happen for SSO
                except AuthTokenExpiredError:
                    self.auth_token_expired()
                    return

            self.choose_active_workspace()
            self.manager = MerginProjectsManager(self)
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

    def open_configured_url(self, path=None):
        """Opens configured Mergin Maps server url in default browser
        Use optional parameter path to go directly to a specific page, eg. /workspaces
        """
        if self.mc is None:
            url = QUrl("https://merginmaps.com")
        else:
            url = QUrl(self.mc.url)

        if path:
            url_path = url.path()
            while url_path.endswith("/"):
                url_path = url_path[:-1]
            url.setPath(f"{url_path}{path}")
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
            if res == QMessageBox.StandardButton.Yes:
                self.iface.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, browser)

    def configure(self):
        """Open plugin configuration dialog."""
        dlg = ConfigurationDialog()
        if dlg.exec():
            try:
                self.mc = create_mergin_client()
                set_qgsexpressionscontext(dlg.server_url(), mc=self.mc)
            except (
                MissingAuthConfigError,
                AuthTokenExpiredError,
                ClientError,
                ValueError,
            ) as e:
                QMessageBox.critical(None, "Login failed", f"Could not login: {str(e)}")
                set_qgsexpressionscontext(dlg.server_url(), mc=None)
                return

            self.on_config_changed()
            self.show_browser_panel()

    def configure_db_sync(self):
        """Open db-sync setup wizard."""
        project_path = QgsProject.instance().homePath()
        if not project_path:
            iface.messageBar().pushMessage(
                "Mergin",
                "Project is not saved, please save project first",
                Qgis.Warning,
            )
            return

        if not check_mergin_subdirs(project_path):
            iface.messageBar().pushMessage(
                "Mergin",
                "Current project is not a Mergin project. Please open a Mergin project first.",
                Qgis.Warning,
            )
            return

        mp = MerginProject(project_path)
        try:
            project_name = mp.project_full_name()
        except InvalidProject as e:
            iface.messageBar().pushMessage(
                "Mergin",
                "Current project is not a Mergin project. Please open a Mergin project first.",
                Qgis.Warning,
            )
            return

        wizard = DbSyncConfigWizard(project_name)
        if not wizard.exec():
            return

    def open_project_history_window(self):
        dlg = VersionViewerDialog(self)
        dlg.exec()

    def show_no_workspaces_dialog(self):
        msg = (
            "Workspace is a place to store your projects and share them with your colleagues. "
            "Click on the button below to create one. \n\n"
            "A minimum of one workspace is required to use Mergin Maps."
        )
        msg_box = QMessageBox(
            QMessageBox.Icon.Critical,
            "You do not have any workspace",
            msg,
            QMessageBox.StandardButton.Close,
        )
        create_button = msg_box.addButton("Create workspace", msg_box.ActionRole)
        create_button.clicked.disconnect()
        create_button.clicked.connect(partial(self.open_configured_url, "/workspaces"))
        msg_box.exec()

    def set_current_workspace(self, workspace):
        """
        Sets the current workspace

        :param workspace: Dict containing workspace's "name" and "id" keys
        """
        settings = QSettings()
        self.current_workspace = workspace
        workspace_id = self.current_workspace.get("id", None)
        settings.setValue("Mergin/lastUsedWorkspaceId", workspace_id)
        if self.has_browser_item():
            self.data_item_provider.root_item.update_client_and_manager(mc=self.mc, manager=self.manager)

        if self.mc.server_type() == ServerType.SAAS and workspace_id:
            # check action required flag
            try:
                service_response = self.mc.workspace_service(workspace_id)
            except ClientError as e:
                return
            except AuthTokenExpiredError:
                self.auth_token_expired()
                return

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

    def choose_active_workspace(self):
        """
        Called after connecting to server.
        Chooses and sets the current workspace based on workspace availability and last used workspace.
        """
        user_info = self.mc.user_info()
        workspaces = user_info.get("workspaces", None)
        if not workspaces:
            # User has no workspaces
            self.show_no_workspaces_dialog()
            self.current_workspace = dict()
            return

        if len(workspaces) == 1:
            workspace = workspaces[0]
        else:
            settings = QSettings()
            previous_workspace = settings.value("Mergin/lastUsedWorkspaceId", None, int)
            workspace = None
            for ws in workspaces:
                if previous_workspace == ws["id"]:
                    workspace = ws
                    break

        if not workspace:
            for ws in workspaces:
                if user_info["preferred_workspace"] == ws["id"]:
                    workspace = ws
                    break

        self.set_current_workspace(workspace)

    def create_new_project(self):
        """Open new Mergin Maps project creation dialog."""
        check_result = unsaved_project_check()
        if check_result == UnsavedChangesStrategy.HasUnsavedChanges:
            return
        if not self.manager:
            QMessageBox.warning(None, "Create Mergin Maps Project", "Plugin not configured!")
            return

        user_info = self.mc.user_info()
        workspaces = user_info.get("workspaces", None)
        if not workspaces and workspaces is not None:
            self.show_no_workspaces_dialog()
            self.current_workspace = dict()
            return

        default_workspace = self.current_workspace.get("name", None)

        wizard = NewMerginProjectWizard(self.manager, user_info=user_info, default_workspace=default_workspace)
        if not wizard.exec():
            return  # cancelled
        if self.has_browser_item():
            # make sure the item has the link between remote and local project we have just added
            self.data_item_provider.root_item.depopulate()
            self.data_item_provider.root_item.reload()

    def current_project_sync(self):
        """Synchronise current Mergin Maps project."""
        self.manager.project_status(self.mergin_proj_dir)

    def find_project(self):
        """Open new Find Mergin Maps project dialog"""
        dlg = ProjectSelectionDialog(self.mc, self.current_workspace.get("name", None))
        dlg.new_project_clicked.connect(self.create_new_project)
        dlg.switch_workspace_clicked.connect(self.switch_workspace)
        dlg.open_project_clicked.connect(self.manager.open_project)
        dlg.download_project_clicked.connect(self.manager.download_project)

        try:
            workspaces = self.mc.workspaces_list()
            dlg.enable_workspace_switching(len(workspaces) > 1)
        except:
            pass

        dlg.exec()

    def switch_workspace(self):
        """Open new Switch workspace dialog"""
        try:
            workspaces = self.mc.workspaces_list()
        except (URLError, ClientError) as e:
            return  # Server does not support workspaces
        except AuthTokenExpiredError:
            self.auth_token_expired()
            return

        if not workspaces:
            self.show_no_workspaces_dialog()
            self.current_workspace = dict()
            return

        dlg = WorkspaceSelectionDialog(workspaces)
        dlg.manage_workspaces_clicked.connect(self.open_configured_url)
        if not dlg.exec():
            return

        workspace = dlg.get_workspace()
        self.set_current_workspace(workspace)

    def explore_public_projects(self):
        """Open new Explore public Mergin Maps projects dialog"""
        dlg = PublicProjectSelectionDialog(self.mc)
        dlg.open_project_clicked.connect(self.manager.open_project)
        dlg.download_project_clicked.connect(self.manager.download_project)
        dlg.exec()

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
            set_qgis_project_mergin_variables(self.mergin_proj_dir)

    def add_context_menu_actions(self, layers):
        provider_names = "vectortile"
        if Qgis.versionInt() >= 33200:
            provider_names = (
                "xyzvectortiles",
                "arcgisvectortileservice",
                "vtpkvectortiles",
            )
        for l in layers:
            if l.dataProvider().name() in provider_names:
                self.iface.addCustomActionForLayer(self.action_export_mbtiles, l)

    def unload(self):
        if self.iface is not None:
            # Disconnect Mergin related signals
            self.iface.projectRead.disconnect(self.on_qgis_project_changed)
            self.iface.newProjectCreated.disconnect(self.on_qgis_project_changed)

            for action in self.actions:
                self.iface.removePluginMenu(self.menu, action)
                self.iface.removeToolBarIcon(action)
            del self.toolbar

            self.iface.removeCustomActionForLayerType(self.action_show_changes)

            self.iface.unregisterProjectPropertiesWidgetFactory(self.mergin_project_config_factory)

        remove_project_variables()
        QgsExpressionContextUtils.removeGlobalVariable("mergin_username")
        QgsExpressionContextUtils.removeGlobalVariable("mm_username")
        QgsExpressionContextUtils.removeGlobalVariable("mergin_url")
        QgsExpressionContextUtils.removeGlobalVariable("mm_url")
        QgsExpressionContextUtils.removeGlobalVariable("mergin_full_name")
        QgsExpressionContextUtils.removeGlobalVariable("mm_full_name")
        QgsExpressionContextUtils.removeGlobalVariable("mergin_user_email")
        QgsExpressionContextUtils.removeGlobalVariable("mm_user_email")
        QgsApplication.instance().dataItemProviderRegistry().removeProvider(self.data_item_provider)
        self.data_item_provider = None
        # this is crashing qgis on exit
        # self.iface.browserModel().reload()

        QgsApplication.processingRegistry().removeProvider(self.provider)

    def view_local_changes(self):
        project_path = QgsProject.instance().homePath()
        if not project_path:
            iface.messageBar().pushMessage(
                "Mergin",
                "Project is not saved, can not compute local changes",
                Qgis.Warning,
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
        dlg_diff_viewer.exec()

    def export_vector_tiles(self):
        selected_layers = self.iface.layerTreeView().selectedLayersRecursive()
        params = {}
        for layer in selected_layers:
            if layer.type() != QgsMapLayer.VectorTileLayer:
                continue

            params["INPUT"] = layer
            break

        processing.execAlgorithmDialog("mergin:downloadvectortiles", params)

    def auth_token_expired(self):
        QMessageBox.information(
            self.iface.mainWindow(),
            "SSO login has expired",
            "Your SSO login has expired. To access your remote projects and be able to synchronize, you need to log in again.",
        )

        self.configure()
