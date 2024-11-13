# GPLv3 license
# Copyright Lutra Consulting Limited

from collections import deque
import os
import math

from qgis.PyQt import uic, QtCore
from qgis.PyQt.QtWidgets import (
    QDialog,
    QAction,
    QListWidgetItem,
    QPushButton,
    QMenu,
    QMessageBox,
    QAbstractItemView,
    QToolButton,
)
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel, QIcon, QFont, QColor
from qgis.PyQt.QtCore import (
    QStringListModel,
    Qt,
    QSettings,
    QModelIndex,
    QAbstractTableModel,
    QThread,
    pyqtSignal,
    QItemSelectionModel,
)

from qgis.utils import iface
from qgis.core import (
    QgsProject,
    QgsMessageLog,
    QgsApplication,
    QgsFeatureRequest,
    QgsVectorLayerCache,
    # Used to filter background map
    QgsRasterLayer,
    QgsTiledSceneLayer,
    QgsVectorTileLayer,
)
from qgis.gui import QgsMapToolPan, QgsAttributeTableModel, QgsAttributeTableFilterModel


from .utils import (
    ClientError,
    icon_path,
    mergin_project_local_path,
    PROJS_PER_PAGE,
    contextual_date,
    is_versioned_file,
    icon_path,
    format_datetime,
    parse_user_agent,
    icon_for_layer,
)

from .mergin.merginproject import MerginProject
from .mergin.utils import bytes_to_human_size, int_version

from .mergin import MerginClient
from .diff import make_version_changes_layers


ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_versions_viewer.ui")


class VersionsTableModel(QAbstractTableModel):
    VERSION = Qt.UserRole + 1
    VERSION_NAME = Qt.UserRole + 2

    def __init__(self, parent=None):
        super().__init__(parent)

        # Keep ordered
        self.versions = deque()

        self.oldest = None
        self.latest = None

        self.headers = ["Version", "Author", "Created"]

        self.current_version = None

    def latest_version(self):
        if len(self.versions) == 0:
            return None
        return int_version(self.versions[0]["name"])

    def oldest_version(self):
        if len(self.versions) == 0:
            return None
        return int_version(self.versions[-1]["name"])

    def rowCount(self, parent: QModelIndex):
        return len(self.versions)

    def columnCount(self, parent: QModelIndex) -> int:
        return len(self.headers)

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.headers[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        idx = index.row()
        if role == Qt.DisplayRole:
            if index.column() == 0:
                if self.versions[idx]["name"] == self.current_version:
                    return f'{self.versions[idx]["name"]} (local)'
                return self.versions[idx]["name"]
            if index.column() == 1:
                return self.versions[idx]["author"]
            if index.column() == 2:
                return contextual_date(self.versions[idx]["created"])
        elif role == Qt.FontRole:
            if self.versions[idx]["name"] == self.current_version:
                font = QFont()
                font.setBold(True)
                return font
        elif role == Qt.ToolTipRole:
            if index.column() == 2:
                return format_datetime(self.versions[idx]["created"])
        elif role == VersionsTableModel.VERSION:
            return int_version(self.versions[idx]["name"])
        elif role == VersionsTableModel.VERSION_NAME:
            return self.versions[idx]["name"]
        else:
            return None

    def insertRows(self, row, count, parent=QModelIndex()):
        self.beginInsertRows(parent, row, row + count - 1)
        self.endInsertRows()

    def clear(self):
        self.beginResetModel()
        self.versions.clear()
        self.endResetModel()

    def add_versions(self, versions):
        self.insertRows(len(self.versions) - 1, len(versions))
        self.versions.extend(versions)
        self.layoutChanged.emit()

    def prepend_versions(self, versions):
        self.insertRows(0, len(versions))
        self.versions.extendleft(versions)
        self.layoutChanged.emit()

    def item_from_index(self, index):
        return self.versions[index.row()]


class ChangesetsDownloader(QThread):
    """
    Class to download version changesets in background worker thread
    """

    finished = pyqtSignal(str)

    def __init__(self, mc, mp, version):
        """
        ChangesetsDownloader constructor

        :param mc: MerginClient instance
        :param mp: MerginProject instance
        :param version: project version to download
        """
        super(ChangesetsDownloader, self).__init__()
        self.mc = mc
        self.mp = mp
        self.version = version

    def run(self):
        version_info = self.mc.project_version_info(self.mp.project_id(), version=f"v{self.version}")

        files_updated = version_info["changes"]["updated"]

        # if file not in project_version_info # skip as well
        if not version_info["changesets"]:
            self.finished.emit("This version does not contain changes in the project layers.")
            return

        files_updated = [f for f in files_updated if is_versioned_file(f["path"])]

        if not files_updated:
            self.finished.emit("This version does not contain changes in the project layers.")
            return

        has_history = any("diff" in f for f in files_updated)
        if not has_history:
            self.finished.emit("This version does not contain changes in the project layers.")
            return

        for f in files_updated:
            if self.isInterruptionRequested():
                return

            if "diff" not in f:
                continue
            file_diffs = self.mc.download_file_diffs(self.mp.dir, f["path"], [f"v{self.version}"])
            full_gpkg = self.mp.fpath_cache(f["path"], version=f"v{self.version}")
            if not os.path.exists(full_gpkg):
                self.mc.download_file(self.mp.dir, f["path"], full_gpkg, f"v{self.version}")

        if self.isInterruptionRequested():
            self.quit()
            return

        self.finished.emit("")


class VersionsFetcher(QThread):

    finished = pyqtSignal(list)

    def __init__(self, mc: MerginClient, project_path, model: VersionsTableModel):
        super(VersionsFetcher, self).__init__()
        self.mc = mc
        self.project_path = project_path
        self.model = model

        self.current_page = 1
        self.per_page = 50

        version_count = self.mc.project_versions_count(self.project_path)
        self.nb_page = math.ceil(version_count / self.per_page)

    def run(self):
        self.fetch_another_page()

    def has_more_page(self):
        return self.current_page <= self.nb_page

    def fetch_another_page(self):
        if self.has_more_page() == False:
            return
        versions = self.mc.project_versions_page(
            self.project_path, self.current_page, per_page=self.per_page, descending=True
        )
        self.model.add_versions(versions)

        self.current_page += 1


class VersionViewerDialog(QDialog):
    """
    The class is constructed in a way that the flow of the code follow the flow the UI
    The UI is read from left to right and each splitter is read from top to bottom

    The __init__ method follow this pattern after varaible initiatlization
    the methods of the class also follow this pattern
    """

    def __init__(self, mc, parent=None):

        QDialog.__init__(self, parent)
        self.ui = uic.loadUi(ui_file, self)

        self.mc = mc

        self.project_path = mergin_project_local_path()
        self.mp = MerginProject(self.project_path)

        self.set_splitters_state()

        self.versionModel = VersionsTableModel()
        self.history_treeview.setModel(self.versionModel)
        self.history_treeview.verticalScrollBar().valueChanged.connect(self.on_scrollbar_changed)

        self.selectionModel: QItemSelectionModel = self.history_treeview.selectionModel()
        self.selectionModel.currentChanged.connect(self.current_version_changed)

        self.has_selected_latest = False

        self.fetcher = VersionsFetcher(self.mc, self.mp.project_full_name(), self.versionModel)
        self.diff_downloader = None

        self.fetcher.fetch_another_page()

        height = 30
        self.toolbar.setMinimumHeight(height)

        self.history_control.setMinimumHeight(height)
        self.history_control.setVisible(False)

        self.toggle_layers_action = QAction(
            QgsApplication.getThemeIcon("/mActionAddLayer.svg"), "Hide background layers", self
        )
        self.toggle_layers_action.setCheckable(True)
        self.toggle_layers_action.setChecked(True)
        self.toggle_layers_action.toggled.connect(self.toggle_project_layers)

        # We use a ToolButton instead of simple action to dislay both icon AND text
        self.toggle_layers_button = QToolButton()
        self.toggle_layers_button.setDefaultAction(self.toggle_layers_action)
        self.toggle_layers_button.setText("Show background layers")
        self.toggle_layers_button.setToolTip(
            "Toggle the display of background layer(Raster and tiles) in the current project"
        )
        self.toggle_layers_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toolbar.addWidget(self.toggle_layers_button)

        self.toolbar.addSeparator()

        self.zoom_full_action = QAction(QgsApplication.getThemeIcon("/mActionZoomFullExtent.svg"), "Zoom Full", self)
        self.zoom_full_action.triggered.connect(self.zoom_full)

        self.toolbar.addAction(self.zoom_full_action)

        self.zoom_selected_action = QAction(
            QgsApplication.getThemeIcon("/mActionZoomToSelected.svg"), "Zoom To Selection", self
        )
        self.zoom_selected_action.triggered.connect(self.zoom_selected)

        self.toolbar.addAction(self.zoom_selected_action)

        btn_add_changes = QPushButton("Add to project")
        btn_add_changes.setIcon(QgsApplication.getThemeIcon("/mActionAdd.svg"))
        menu = QMenu()
        add_current_action = menu.addAction(QIcon(icon_path("file-plus.svg")), "Add current changes layer to project")
        add_current_action.triggered.connect(self.add_current_to_project)
        add_all_action = menu.addAction(QIcon(icon_path("folder-plus.svg")), "Add all changes layers to project")
        add_all_action.triggered.connect(self.add_all_to_project)
        btn_add_changes.setMenu(menu)

        self.toolbar.addWidget(btn_add_changes)
        self.toolbar.setIconSize(iface.iconSize())

        self.map_canvas.enableAntiAliasing(True)
        self.map_canvas.setSelectionColor(QColor(Qt.cyan))
        self.pan_tool = QgsMapToolPan(self.map_canvas)
        self.map_canvas.setMapTool(self.pan_tool)

        self.current_diff = None
        self.diff_layers = []
        self.filter_model = None
        self.layer_list.currentRowChanged.connect(self.diff_layer_changed)

        self.icons = {
            "added": "plus.svg",
            "removed": "trash.svg",
            "updated": "pencil.svg",
            "renamed": "pencil.svg",
            "table": "table.svg",
        }
        self.model_detail = QStandardItemModel()
        self.model_detail.setHorizontalHeaderLabels(["Details"])

        self.details_treeview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.details_treeview.setModel(self.model_detail)

        self.versionModel.current_version = self.mp.version()

    def exec(self):

        try:
            ws_id = self.mp.workspace_id()
        except ClientError as e:
            QMessageBox.warning(None, "Client Error", str(e))
            return

        # check if user has permissions
        try:
            usage = self.mc.workspace_usage(ws_id)
            if not usage["view_history"]["allowed"]:
                QMessageBox.warning(
                    None, "Upgrade required", "To view the project history, please upgrade your subscription plan."
                )
                return
        except ClientError:
            # Some versions e.g CE, EE edition doesn't have
            pass
        super().exec()

    def closeEvent(self, event):
        self.save_splitters_state()
        QDialog.closeEvent(self, event)

    def save_splitters_state(self):
        settings = QSettings()
        settings.setValue("Mergin/VersionViewerSplitterSize", self.splitter_map_table.saveState())
        settings.setValue("Mergin/VersionViewerSplitterVericalSize", self.splitter_vertical.saveState())

    def set_splitters_state(self):
        settings = QSettings()
        state_vertical = settings.value("Mergin/VersionViewerSplitterVericalSize")
        if state_vertical:
            self.splitter_vertical.restoreState(state_vertical)
        else:
            self.splitter_vertical.setSizes([120, 200, 40])

        do_calc_height = True
        state = settings.value("Mergin/VersionViewerSplitterSize")
        if state:
            self.splitter_map_table.restoreState(state)

            if self.splitter_map_table.sizes()[0] != 0:
                do_calc_height = False

        if do_calc_height:
            height = max([self.map_canvas.minimumSizeHint().height(), self.attribute_table.minimumSizeHint().height()])
            self.splitter_map_table.setSizes([height, height])

    def fetch_from_server(self):

        if self.fetcher and self.fetcher.isRunning():
            # Only fetching when previous is finshed
            return
        else:
            self.fetcher.start()

    def on_scrollbar_changed(self, value):

        if self.ui.history_treeview.verticalScrollBar().maximum() <= value:
            self.fetch_from_server()

    def current_version_changed(self, current_index, previous_index):
        # Update the ui when the selected version change
        item = self.versionModel.item_from_index(current_index)
        version_name = item["name"]
        version = int_version(item["name"])

        self.setWindowTitle(f"Changes Viewer | {version_name}")

        self.version_details = self.mc.project_version_info(self.mp.project_id(), version_name)
        self.populate_details()
        self.details_treeview.expandAll()

        # Reset layer list
        self.layer_list.clear()

        if not os.path.exists(os.path.join(self.project_path, ".mergin", ".cache", f"v{version}")):

            self.stackedWidget.setCurrentIndex(1)
            self.label_info.setText("Loading version info…")

            if self.diff_downloader and self.diff_downloader.isRunning():
                self.diff_downloader.requestInterruption()

            self.diff_downloader = ChangesetsDownloader(self.mc, self.mp, version)
            self.diff_downloader.finished.connect(lambda msg: self.show_version_changes(version))
            self.diff_downloader.start()
        else:
            self.show_version_changes(version)

    def populate_details(self):
        self.edit_project_size.setText(bytes_to_human_size(self.version_details["project_size"]))
        self.edit_created.setText(format_datetime(self.version_details["created"]))
        self.edit_user_agent.setText(parse_user_agent(self.version_details["user_agent"]))
        self.edit_user_agent.setToolTip(self.version_details["user_agent"])

        self.model_detail.clear()
        root_item = QStandardItem(f"Changes in version {self.version_details['name']}")
        self.model_detail.appendRow(root_item)
        for category in self.version_details["changes"]:
            for item in self.version_details["changes"][category]:
                path = item["path"]
                item = self._get_icon_item(category, path)
                if is_versioned_file(path):
                    if path in self.version_details["changesets"]:
                        for sub_item in self._versioned_file_summary_items(
                            self.version_details["changesets"][path]["summary"]
                        ):
                            item.appendRow(sub_item)
                root_item.appendRow(item)

    def _get_icon_item(self, key, text):
        path = icon_path(self.icons[key])
        item = QStandardItem(text)
        item.setIcon(QIcon(path))
        return item

    def _versioned_file_summary_items(self, summary):
        items = []
        for s in summary:
            table_name_item = self._get_icon_item("table", s["table"])
            for row in self._table_summary_items(s):
                table_name_item.appendRow(row)
            items.append(table_name_item)

        return items

    def _table_summary_items(self, summary):
        return [QStandardItem("{}: {}".format(k, summary[k])) for k in summary if k != "table"]

    def toggle_project_layers(self, checked):
        if checked:
            self.toggle_layers_button.setText("Hide background layers")
        else:
            self.toggle_layers_button.setText("Show background layers")

        layers = self.collect_layers(checked)
        self.update_canvas_layers(layers)

    def update_canvas(self, layers):

        if self.current_diff.isSpatial() == False:
            self.map_canvas.setEnabled(False)
            self.save_splitters_state()
            self.splitter_map_table.setSizes([0, 1])
        else:
            self.map_canvas.setEnabled(True)
            self.set_splitters_state()

        self.update_canvas_layers(layers)
        self.update_canvas_extend(layers)

    def update_canvas_layers(self, layers):
        self.map_canvas.setLayers(layers)
        self.map_canvas.refresh()

    def update_canvas_extend(self, layers):
        self.map_canvas.setDestinationCrs(QgsProject.instance().crs())

        if layers:
            extent = layers[0].extent()
            d = min(extent.width(), extent.height())
            if d == 0:
                d = 1
            extent = extent.buffered(d * 0.07)

            extent = self.map_canvas.mapSettings().layerExtentToOutputExtent(layers[0], extent)

            self.map_canvas.setExtent(extent)
        self.map_canvas.refresh()

    def show_version_changes(self, version):
        self.diff_layers.clear()

        layers = make_version_changes_layers(QgsProject.instance().homePath(), version)
        for vl in layers:
            self.diff_layers.append(vl)
            icon = icon_for_layer(vl)

            summary = self.find_changeset_summary_for_layer(vl.name(), self.version_details["changesets"])
            additional_info = []
            if summary["insert"]:
                additional_info.append(f"{summary['insert']} added")
            if summary["update"]:
                additional_info.append(f"{summary['update']} updated")
            if summary["delete"]:
                additional_info.append(f"{summary['delete']} deleted")

            additional_summary = "\n" + ",".join(additional_info)

            self.layer_list.addItem(QListWidgetItem(icon, vl.name() + additional_summary))

        if len(self.diff_layers) >= 1:
            self.toolbar.setEnabled(True)
            self.layer_list.setCurrentRow(0)
            self.stackedWidget.setCurrentIndex(0)
            self.tabWidget.setCurrentIndex(0)
            self.tabWidget.setTabEnabled(0, True)
            layers = self.collect_layers(self.toggle_layers_action.isChecked())
            self.update_canvas(layers)
        else:
            self.toolbar.setEnabled(False)
            self.stackedWidget.setCurrentIndex(1)
            self.label_info.setText("No visual changes")
            self.tabWidget.setCurrentIndex(1)
            self.tabWidget.setTabEnabled(0, False)

    def collect_layers(self, checked: bool):
        if checked:
            layers = iface.mapCanvas().layers()

            # Filter only "Background" type
            whitelist_backgound_layer_types = [QgsRasterLayer, QgsVectorTileLayer, QgsTiledSceneLayer]
            layers = [layer for layer in layers if type(layer) in whitelist_backgound_layer_types]
        else:
            layers = []

        if self.current_diff:
            layers.insert(0, self.current_diff)

        return layers

    def diff_layer_changed(self, index: int):
        if index > len(self.diff_layers) or index < 0:
            return

        self.map_canvas.setLayers([])
        self.attribute_table.clearSelection()

        self.current_diff = self.diff_layers[index]

        self.layer_cache = QgsVectorLayerCache(self.current_diff, 1000)
        self.layer_cache.setCacheGeometry(False)

        self.table_model = QgsAttributeTableModel(self.layer_cache)
        self.table_model.setRequest(QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry).setLimit(100))

        self.filter_model = QgsAttributeTableFilterModel(self.map_canvas, self.table_model)

        self.layer_cache.setParent(self.table_model)

        self.attribute_table.setModel(self.filter_model)
        self.table_model.loadLayer()

        config = self.current_diff.attributeTableConfig()
        self.filter_model.setAttributeTableConfig(config)
        self.attribute_table.setAttributeTableConfig(config)

        layers = self.collect_layers(self.toggle_layers_action.isChecked())
        self.update_canvas(layers)

    def add_current_to_project(self):
        if self.current_diff:
            QgsProject.instance().addMapLayer(self.current_diff)

    def add_all_to_project(self):
        for layer in self.diff_layers:
            QgsProject.instance().addMapLayer(layer)

    def zoom_full(self):
        if self.current_diff:
            self.map_canvas.setExtent(self.current_diff.extent())
            self.map_canvas.refresh()

    def zoom_selected(self):
        if self.current_diff:
            self.map_canvas.zoomToSelected([self.current_diff])
            self.map_canvas.refresh()

    def find_changeset_summary_for_layer(self, layer_name: str, changesets: dict):
        for gpkg_changes in changesets.values():
            for summary in gpkg_changes["summary"]:
                if summary["table"] == layer_name:
                    return summary
