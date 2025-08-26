# GPLv3 license
# Copyright Lutra Consulting Limited

import os

from qgis.PyQt import uic
from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import QWizard, QFileDialog

from qgis.gui import QgsFileWidget
from qgis.core import (
    QgsProject,
    QgsProviderRegistry,
    QgsApplication,
    QgsAuthMethodConfig,
)

from .utils_auth import get_stored_mergin_server_url, get_mergin_username_password

base_dir = os.path.dirname(__file__)
ui_direction_page, base_direction_page = uic.loadUiType(os.path.join(base_dir, "ui", "ui_sync_direction_page.ui"))
ui_gpkg_select_page, base_gpkg_select_page = uic.loadUiType(os.path.join(base_dir, "ui", "ui_gpkg_selection_page.ui"))
ui_db_select_page, base_db_select_page = uic.loadUiType(os.path.join(base_dir, "ui", "ui_db_selection_page.ui"))
ui_config_page, base_config_page = uic.loadUiType(os.path.join(base_dir, "ui", "ui_config_file_page.ui"))

SYNC_DIRECTION_PAGE = 0
GPKG_SELECT_PAGE = 1
DB_SELECT_PAGE = 2
CONFIG_PAGE = 3


class SyncDirectionPage(ui_direction_page, base_direction_page):
    """Initial wizard page with sync direction selector."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.parent = parent

        self.ledit_sync_direction.hide()
        self.registerField("init_from*", self.ledit_sync_direction)

        self.radio_from_project.toggled.connect(self.update_direction)
        self.radio_from_db.toggled.connect(self.update_direction)

    def update_direction(self, checked):
        if self.radio_from_project.isChecked():
            self.ledit_sync_direction.setText("gpkg")
        else:
            self.ledit_sync_direction.setText("db")

    def nextId(self):
        """Decide about the next page based on selected sync direction."""
        if self.radio_from_project.isChecked():
            return GPKG_SELECT_PAGE
        return DB_SELECT_PAGE


class GpkgSelectionPage(ui_gpkg_select_page, base_gpkg_select_page):
    """Wizard page for selecting GPKG file."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.parent = parent

        self.ledit_gpkg_file.hide()
        self.registerField("sync_file", self.ledit_gpkg_file)

    def initializePage(self):
        direction = self.field("init_from")
        if direction == "gpkg":
            self.label.setText("Pick a GeoPackage file that contains data to be synchronised")
            self.file_edit_gpkg.setStorageMode(QgsFileWidget.GetFile)
        else:
            self.label.setText("Pick a GeoPackage file that will contain synchronised data")
            self.file_edit_gpkg.setStorageMode(QgsFileWidget.SaveFile)

        self.file_edit_gpkg.setDialogTitle(self.tr("Select file"))
        settings = QSettings()
        self.file_edit_gpkg.setDefaultRoot(
            settings.value("Mergin/lastUsedDirectory", QgsProject.instance().homePath(), str)
        )
        self.file_edit_gpkg.setFilter("GeoPackage files (*.gpkg *.GPKG)")
        self.file_edit_gpkg.fileChanged.connect(self.ledit_gpkg_file.setText)

    def nextId(self):
        """Decide about the next page based on selected sync direction."""
        direction = self.field("init_from")
        if direction == "gpkg":
            return DB_SELECT_PAGE
        return CONFIG_PAGE


class DatabaseSelectionPage(ui_db_select_page, base_db_select_page):
    """Wizard page for selecting database and schema."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.parent = parent

        self.ledit_sync_schema.hide()
        self.populate_connections()

        self.registerField(
            "connection*",
            self.cmb_db_conn,
            "currentText",
            self.cmb_db_conn.currentTextChanged,
        )
        self.registerField("sync_schema*", self.ledit_sync_schema)
        self.registerField("internal_schema*", self.line_edit_internal_schema)
        self.cmb_db_conn.currentTextChanged.connect(self.populate_schemas)

    def initializePage(self):
        self.direction = self.field("init_from")
        if self.direction == "gpkg":
            self.label_sync_schema.setText("Schema name for sync (will be created)")
            # use line edit for schema name
            self.stackedWidget.setCurrentIndex(0)
            self.line_edit_sync_schema.textChanged.connect(self.schema_changed)
        else:
            self.label_sync_schema.setText("Existing schema name for sync")
            # use combobox to select existing schema
            self.stackedWidget.setCurrentIndex(1)
            self.cmb_sync_schema.currentTextChanged.connect(self.schema_changed)

        # pre-fill internal schema name
        self.line_edit_internal_schema.setText("merginmaps_db_sync")

    def cleanupPage(self):
        if self.direction == "gpkg":
            self.line_edit_sync_schema.textChanged.disconnect()
        else:
            self.cmb_sync_schema.currentTextChanged.disconnect()

    def schema_changed(self, schema_name):
        self.line_edit_internal_schema.setText(f"{schema_name}_db_sync")
        self.ledit_sync_schema.setText(schema_name)

    def populate_connections(self):
        metadata = QgsProviderRegistry.instance().providerMetadata("postgres")
        connections = metadata.dbConnections()
        for k, v in connections.items():
            self.cmb_db_conn.addItem(k, v)

        self.cmb_db_conn.setCurrentIndex(-1)

    def populate_schemas(self):
        connection = self.cmb_db_conn.currentData()
        if connection:
            self.cmb_sync_schema.clear()
            self.cmb_sync_schema.addItems(connection.schemas())

    def nextId(self):
        """Decide about the next page based on selected sync direction."""
        if self.direction == "gpkg":
            return CONFIG_PAGE
        return GPKG_SELECT_PAGE


class ConfigFilePage(ui_config_page, base_config_page):
    """Wizard page with generated config file."""

    def __init__(self, project_name, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.parent = parent

        self.project_name = project_name

        self.btn_save_config.clicked.connect(self.save_config)

    def initializePage(self):
        self.text_config_file.setPlainText(self.generate_config())

    def save_config(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save file", os.path.expanduser("~"), "YAML files (*.yml *.YML)"
        )
        if file_path:
            if not file_path.lower().endswith(".yml"):
                file_path += ".yml"

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(self.text_config_file.toPlainText())

    def generate_config(self):
        url = get_stored_mergin_server_url()
        user, password = get_mergin_username_password()
        metadata = QgsProviderRegistry.instance().providerMetadata("postgres")
        conn = metadata.dbConnections()[self.field("connection")]
        decoded_uri = metadata.decodeUri(conn.uri())
        conn_string = []
        if "host" in decoded_uri:
            conn_string.append(f"host={decoded_uri['host']}")
        if "port" in decoded_uri:
            conn_string.append(f"port={decoded_uri['port']}")
        if "dbname" in decoded_uri:
            conn_string.append(f"dbname={decoded_uri['dbname']}")

        if "authcfg" in decoded_uri:
            auth_id = decoded_uri["authcfg"]
            auth_manager = QgsApplication.authManager()
            auth_config = QgsAuthMethodConfig()
            auth_manager.loadAuthenticationConfig(auth_id, auth_config, True)
            conn_string.append(f"user={auth_config.config('username')}")
            conn_string.append(f"password={auth_config.config('password')}")
        else:
            if "username" in decoded_uri:
                user_name = decoded_uri["username"].strip("'")
                conn_string.append(f"user={user_name}")
            if "password" in decoded_uri:
                password = decoded_uri["password"].strip("'")
                conn_string.append(f"password={password}")

        cfg = (
            "mergin:\n"
            f"  url: {url}\n"
            f"  username: {user}\n"
            f"  password: {password}\n"
            f"init_from: {self.field('init_from')}\n"
            "connections:\n"
            f"  - driver: postgres\n"
            f"    conn_info: \"{' '.join(conn_string)}\"\n"
            f"    modified: {self.field('sync_schema')}\n"
            f"    base: {self.field('internal_schema')}\n"
            f"    mergin_project: {self.project_name}\n"
            f"    sync_file: {os.path.split(self.field('sync_file'))[1]}\n"
            f"daemon:\n"
            f"  sleep_time: 10\n"
        )

        return cfg


class DbSyncConfigWizard(QWizard):
    """Wizard for configuring db-sync."""

    def __init__(self, project_name, parent=None):
        """Create a wizard"""
        super().__init__(parent)

        self.setWindowTitle("Create db-sync configuration")

        self.project_name = project_name

        self.start_page = SyncDirectionPage(self)
        self.setPage(SYNC_DIRECTION_PAGE, self.start_page)

        self.gpkg_page = GpkgSelectionPage(parent=self)
        self.setPage(GPKG_SELECT_PAGE, self.gpkg_page)

        self.db_page = DatabaseSelectionPage(parent=self)
        self.setPage(DB_SELECT_PAGE, self.db_page)

        self.config_page = ConfigFilePage(self.project_name, parent=self)
        self.setPage(CONFIG_PAGE, self.config_page)
