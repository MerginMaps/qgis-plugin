import os
import yaml
import typing
import re

try:
    import psycopg2

    has_psycopg2 = True
except ImportError:
    has_psycopg2 = False

from qgis.core import (
    QgsProject,
    QgsDataSourceUri,
    QgsMapLayer,
    Qgis,
    QgsVectorLayer,
)
from qgis.gui import QgsFileWidget, QgisInterface
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QWizard, QLineEdit


base_dir = os.path.dirname(__file__)
ui_select_dbsync_page, base_select_dbsync_page = uic.loadUiType(
    os.path.join(base_dir, "ui", "ui_switch_datasources_select_dbsync.ui")
)
ui_select_qgsproject_page, base_select_qgsproject_page = uic.loadUiType(
    os.path.join(base_dir, "ui", "ui_switch_datasources_select_updated_project.ui")
)


DBSYNC_PAGE = 0
QGS_PROJECT_PAGE = 1


class Connection:
    def __init__(self, driver: str, db_connection_info: str, db_schema: str, sync_file: str) -> None:
        self.driver = driver
        self.db_connection_info = db_connection_info
        self.db_schema = db_schema
        self.sync_file = sync_file
        self.valid: bool = False
        self.db_tables: typing.List[str] = []

        if has_psycopg2:
            try:
                conn = psycopg2.connect(self.db_connection_info)
            except Exception as e:
                return
            cur = conn.cursor()
            cur.execute(f"SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = '{self.db_schema}'")
            self.db_tables = [x[0] for x in cur.fetchall()]
            self.valid = True
            conn.close()
        else:
            self.valid = True

    def convert_to_postgresql_layer(self, gpkg_layer: QgsVectorLayer) -> None:
        layer_uri = gpkg_layer.dataProvider().dataSourceUri()

        extract = re.search("\|layername=(.+)", layer_uri)

        if extract:
            layer_name = extract.group(1)

            if layer_name in self.db_tables:
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

    selectDbSyncConfig: QgsFileWidget
    ldbsync_config_file: QLineEdit

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.parent = parent

        self.ldbsync_config_file.hide()

        self.registerField("db_sync_file*", self.ldbsync_config_file)

        self.selectDbSyncConfig.setFilter("DBSync configuration files (*.yaml *.YAML)")
        self.selectDbSyncConfig.fileChanged.connect(self.db_sync_config)

    def db_sync_config(self, path: str) -> None:
        self.ldbsync_config_file.setText(path)

    def nextId(self):
        return QGS_PROJECT_PAGE


class QgsProjectSelectionPage(ui_select_qgsproject_page, base_select_qgsproject_page):
    """Wizard page with selection od QgsProject file selector."""

    selectQgisProject: QgsFileWidget
    lqgsproject_file: QLineEdit

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.parent = parent

        self.lqgsproject_file.hide()

        self.registerField("qgis_project*", self.lqgsproject_file)

        self.selectQgisProject.setFilter("QGIS files (*.qgz *.qgs *.QGZ *.QGS)")
        self.selectQgisProject.setStorageMode(QgsFileWidget.StorageMode.SaveFile)
        self.selectQgisProject.fileChanged.connect(self.qgis_project)

    def qgis_project(self, path: str) -> None:
        self.lqgsproject_file.setText(path)


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
        self.read_connections(self.start_page.field("db_sync_file"))

        self.convert_gpkg_layers_to_postgis_sources(self.qgsproject_page.field("qgis_project"))

        return super().accept()

    def read_connections(self, path: str) -> None:
        if path:
            with open(path, mode="r", encoding="utf-8") as stream:
                config = yaml.safe_load(stream)

            self.connections = []
            invalid_connections_info = []

            for conn in config["connections"]:
                connection = Connection(conn["driver"], conn["conn_info"], conn["modified"], conn["sync_file"])
                if connection.valid:
                    self.connections.append(connection)
                else:
                    invalid_connections_info.append(conn["conn_info"])

            if invalid_connections_info:
                self.iface.messageBar().pushMessage(
                    "Mergin",
                    f"Cannot connect to following databases: {'; '.join(invalid_connections_info)}.",
                    level=Qgis.Critical,
                    duration=0,
                )
        else:
            self.connections = []

    def new_project_parent_folder(self) -> str:
        return os.path.dirname(self.qgsproject_page.field("qgis_project"))

    def convert_gpkg_layers_to_postgis_sources(self, result_qgsproject_path: str):
        update_project = QgsProject()
        update_project.read(self.qgis_project.fileName())

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
