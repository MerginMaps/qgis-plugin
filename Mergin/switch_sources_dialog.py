import os
import yaml
import typing
import re
import pathlib

from qgis.core import (
    QgsProject,
    QgsDataSourceUri,
    QgsMapLayer,
    Qgis,
    QgsVectorLayer,
)
from qgis.gui import QgsFileWidget, QgisInterface
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QWizard, QLineEdit, QMessageBox


base_dir = os.path.dirname(__file__)
ui_select_dbsync_page, base_select_dbsync_page = uic.loadUiType(
    os.path.join(base_dir, "ui", "ui_switch_datasources_select_dbsync.ui")
)
ui_select_qgsproject_page, base_select_qgsproject_page = uic.loadUiType(
    os.path.join(base_dir, "ui", "ui_switch_datasources_select_updated_project.ui")
)


DBSYNC_PAGE = 0
QGS_PROJECT_PAGE = 1


class DbSyncConfig:
    def __init__(self, config_file_path: str, base_qgis_project_path: str) -> None:
        self.qgis_project_path = base_qgis_project_path
        self.connections = []

        with open(config_file_path, mode="r", encoding="utf-8") as stream:
            config = yaml.safe_load(stream)

            for conn in config["connections"]:
                connection = Connection(conn["driver"], conn["conn_info"], conn["modified"], conn["sync_file"])
                self.connections.append(connection)

    def convert_gpkg_layers_to_postgis_sources(self, result_qgsproject_path: str):
        update_project = QgsProject()
        update_project.read(self.qgis_project_path)

        project_layers = update_project.mapLayers()

        layer: QgsMapLayer

        for layer_id in project_layers:
            layer = update_project.mapLayer(layer_id)

            for dbsync_connection in self.connections:
                if (
                    layer.dataProvider().name() == "ogr"
                    and dbsync_connection.sync_file in layer.dataProvider().dataSourceUri()
                ):
                    dbsync_connection.convert_to_postgresql_layer(layer)

        update_project.write(result_qgsproject_path)


class Connection:
    def __init__(self, driver: str, db_connection_info: str, db_schema: str, sync_file: str) -> None:
        self.driver = driver
        self.db_connection_info = db_connection_info
        self.db_schema = db_schema
        self.sync_file = sync_file

    def convert_to_postgresql_layer(self, gpkg_layer: QgsVectorLayer) -> None:
        layer_uri = gpkg_layer.dataProvider().dataSourceUri()

        extract = re.search("\|layername=(.+)", layer_uri)

        if extract:
            layer_name = extract.group(1)

            uri = QgsDataSourceUri(self.db_connection_info)
            uri.setSchema(self.db_schema)
            uri.setTable(layer_name)
            uri.setGeometryColumn("geom")  # TODO should this be hardcoded?
            gpkg_layer.setDataSource(uri.uri(), gpkg_layer.name(), "postgres")

    def convert_to_gpkg_layer(self, postgresql_layer: QgsVectorLayer, gpkg_folder: str) -> None:
        gpkg = QgsVectorLayer(f"{gpkg_folder}/{self.sync_file}", "temp", "ogr")
        gpkg_layers = [x.split("!!::!!")[1] for x in gpkg.dataProvider().subLayers()]

        table_name = postgresql_layer.dataProvider().uri().table()

        if table_name in gpkg_layers:
            uri = f"{gpkg_folder}/{self.sync_file}|layername={table_name}"

            postgresql_layer.setDataSource(uri, postgresql_layer.name(), "ogr")


class DBSyncConfigSelectionPage(ui_select_dbsync_page, base_select_dbsync_page):
    """Initial wizard page with selection od dbsync file selector."""

    select_db_sync_config: QgsFileWidget
    hidden_dbsync_config_file: QLineEdit

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.parent = parent

        self.hidden_dbsync_config_file.hide()

        self.registerField("db_sync_file*", self.hidden_dbsync_config_file)

        self.select_db_sync_config.setFilter("DBSync configuration files (*.yaml *.YAML)")
        self.select_db_sync_config.fileChanged.connect(self.db_sync_config)

    def db_sync_config(self, path: str) -> None:
        self.hidden_dbsync_config_file.setText(path)

    def nextId(self):
        return QGS_PROJECT_PAGE


class QgsProjectSelectionPage(ui_select_qgsproject_page, base_select_qgsproject_page):
    """Wizard page with selection od QgsProject file selector."""

    select_qgis_project_name: QgsFileWidget
    hidden_new_qgis_project_file: QLineEdit

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.parent = parent

        self.hidden_new_qgis_project_file.hide()

        self.registerField("qgis_project*", self.hidden_new_qgis_project_file)

        self.select_qgis_project_name.setFilter("QGIS files (*.qgz *.qgs *.QGZ *.QGS)")
        self.select_qgis_project_name.setStorageMode(QgsFileWidget.StorageMode.SaveFile)
        self.select_qgis_project_name.fileChanged.connect(self.qgis_project)

    def qgis_project(self, path: str) -> None:
        folders = [x.name for x in pathlib.Path(path).parent.iterdir() if x.is_dir()]

        if ".mergin" in folders:
            QMessageBox.critical(
                None,
                "Bad project location",
                "The updated project should not be saved within Mergin directory. Please select different location.",
            )
            self.select_qgis_project_name.lineEdit().clear()
            return

        self.hidden_new_qgis_project_file.setText(path)


class ProjectUsePostgreConfigWizard(QWizard):
    """Wizard for changing project layer sources from GPKG to PostgreSQL."""

    def __init__(self, iface: QgisInterface, parent=None):
        """Create a wizard"""
        super().__init__(parent)

        self.iface = iface
        self.setWindowTitle("Create project with layers from PostgreSQL")

        self.connections: typing.List[Connection] = []

        self.qgis_project = QgsProject.instance()

        self.start_page = DBSyncConfigSelectionPage(self)
        self.setPage(DBSYNC_PAGE, self.start_page)

        self.qgsproject_page = QgsProjectSelectionPage(self)
        self.setPage(QGS_PROJECT_PAGE, self.qgsproject_page)

    def accept(self) -> None:
        dbsync = DbSyncConfig(self.start_page.field("db_sync_file"), self.qgis_project.fileName())

        dbsync.convert_gpkg_layers_to_postgis_sources(self.qgsproject_page.field("qgis_project"))

        return super().accept()
