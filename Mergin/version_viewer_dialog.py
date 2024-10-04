from collections import deque
import os

from qgis.PyQt import uic, QtCore
from qgis.PyQt.QtWidgets import QDialog, QAction, QListWidgetItem, QPushButton, QMenu, QMessageBox
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel, QIcon, QFont
from qgis.PyQt.QtCore import QStringListModel, Qt, QSettings, QModelIndex, QAbstractTableModel, QThread, pyqtSignal, QItemSelectionModel

from qgis.utils import iface
from qgis.core import QgsProject, QgsMessageLog, QgsApplication, QgsFeatureRequest, QgsVectorLayerCache
from qgis.gui import QgsGui, QgsMapToolPan, QgsAttributeTableModel, QgsAttributeTableFilterModel


from .utils import (
    ServerType,
    ClientError,
    LoginError,
    InvalidProject,
    check_mergin_subdirs,
    create_mergin_client,
    find_qgis_files,
    get_mergin_auth,
    icon_path,
    mm_symbol_path,
    is_number,
    login_error_message,
    mergin_project_local_path,
    PROJS_PER_PAGE,
    remove_project_variables,
    same_dir,
    unhandled_exception_message,
    unsaved_project_check,
    UnsavedChangesStrategy,
    contextual_date,
    is_versioned_file,
    icon_path,
    format_datetime,
)

from .mergin.merginproject import MerginProject
from .mergin.utils import bytes_to_human_size, int_version

from .mergin import MerginClient
from .diff import make_version_changes_layers, icon_for_layer


ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_draft_versions_viewer.ui")


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

    def canFetchMore(self, parent: QModelIndex) -> bool:
        # Fetch while we are not the the first version
        return self.oldest_version() == None or self.oldest_version() >= 1

    def fetchMore(self, parent: QModelIndex) -> None:
        pass
        # emit
        # fetcher = VersionsFetcher(self.mc,self.mp.project_full_name(), self.model)
        # fetcher.finished.connect(lambda versions: self.model.add_versions(versions))
        # fetcher.start()

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
        info = self.mc.project_info(self.mp.project_full_name(), version=f"v{self.version}")
        files = [f for f in info["files"] if is_versioned_file(f["path"])]
        if not files:
            self.finished.emit("This version does not contain changes in the project layers.")
            return

        has_history = any("diff" in f for f in files)
        if not has_history:
            self.finished.emit("This version does not contain changes in the project layers.")
            return

        for f in files:
            if self.isInterruptionRequested():
                return

            if "diff" not in f:
                continue
            file_diffs = self.mc.download_file_diffs(self.mp.dir, f["path"], [f"v{self.version}"])
            full_gpkg = self.mp.fpath_cache(f["path"], version=f"v{self.version}")
            if not os.path.exists(full_gpkg):
                self.mc.download_file(self.mp.dir, f["path"], full_gpkg, f"v{self.version}")

        self.finished.emit("")


class VersionsFetcher(QThread):

    finished = pyqtSignal(list)

    def __init__(self, mc: MerginClient, project_name, model: VersionsTableModel, is_sync=False):
        super(VersionsFetcher, self).__init__()
        self.mc = mc
        self.project_name = project_name
        self.model = model

        self.is_sync = is_sync

        self.per_page = 50  # server limit

    def run(self):

        if not self.is_sync:
            versions = self.fetch_previous()
        else:
            versions = self.fetch_sync_history()

        self.finished.emit(versions)

    def fetch_previous(self):

        if len(self.model.versions) == 0:
            # initial fetch
            info = self.mc.project_info(self.project_name)
            to = int_version(info["version"])
        else:
            to = self.model.oldest_version()
        since = to - 100
        if since < 0:
            since = 1

        versions = self.mc.project_versions(self.project_name, since=since, to=to)
        versions.reverse()

        return versions

    def fetch_sync_history(self):

        # determine latest
        info = self.mc.project_info(self.project_name)

        latest_server = int_version(info["version"])
        since = self.model.latest_version()

        versions = self.mc.project_versions(self.project_name, since=since, to=latest_server)
        versions.pop()  # Remove the last as we already have it
        versions.reverse()

        return versions


class VersionViewerDialog(QDialog):
    def __init__(self, mc, parent=None):

        QDialog.__init__(self, parent)
        self.ui = uic.loadUi(ui_file, self)

        self.mc = mc
        self.mp = None

        self.project_path = mergin_project_local_path()
        self.mp = MerginProject(self.project_path)

        self.fetcher = None
        self.diff_downloader = None

        self.model = VersionsTableModel()
        self.history_treeview.setModel(self.model)
        
        self.selectionModel = self.history_treeview.selectionModel()

        self.selectionModel.currentChanged.connect(self.currentVersionChanged)

        self.fetch_from_server()

        height = 30
        self.toolbar.setMinimumHeight(height)

        self.history_control.setMinimumHeight(height)
        self.history_control.setVisible(False)

        self.toggle_layers_action = QAction(
            QgsApplication.getThemeIcon("/mActionAddLayer.svg"), "Toggle Project Layers", self
        )
        self.toggle_layers_action.setCheckable(True)
        self.toggle_layers_action.setChecked(True)
        self.toggle_layers_action.toggled.connect(self.toggle_project_layers)
        self.toolbar.addAction(self.toggle_layers_action)

        self.toolbar.addSeparator()

        self.zoom_full_action = QAction(QgsApplication.getThemeIcon("/mActionZoomFullExtent.svg"), "Zoom Full", self)
        self.toolbar.addAction(self.zoom_full_action)

        self.zoom_selected_action = QAction(
            QgsApplication.getThemeIcon("/mActionZoomToSelected.svg"), "Zoom To Selection", self
        )
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

        self.set_splitters_state()

        self.current_diff = None
        self.diff_layers = []
        self.filter_model = None

        self.layer_list.currentRowChanged.connect(self.diff_layer_changed)

        self.show_version_changes(25)
        self.update_canvas(self.diff_layers)
        self.diff_layer_changed(1)

        self.version_details = self.mc.project_version_info(self.mp.project_id(), "v25")

        self.icons = {
            "added": "plus.svg",
            "removed": "trash.svg",
            "updated": "pencil.svg",
            "renamed": "pencil.svg",
            "table": "table.svg",
        }
        self.model_detail = QStandardItemModel()
        self.model_detail.setHorizontalHeaderLabels(["Details"])
        self.details_treeview.setModel(self.model_detail)
        self.populate_details()
        self.details_treeview.expandAll()

        self.model.current_version = self.mp.version()
        self.fetch_from_server()

    def exec(self):

        try:
            ws_id = self.mp.workspace_id()
        except ClientError as e:
            QMessageBox.warning(None, "Client Error", str(e))
            return

        # check if user has permissions
        usage = self.mc.workspace_usage(ws_id)
        if not usage["view_history"]["allowed"]:
            QMessageBox.warning(None, "Permission Error", "The workspace does not allow to view project history.")
            return

        self.reject()
        return

    
    def currentVersionChanged(self, current_index, previous_index):
        item = self.model.item_from_index(current_index)
        version_name = item["name"]
        version = int_version(item["name"])

        self.version_details = self.mc.project_version_info(self.mp.project_id(), version_name)
        self.populate_details()
        self.details_treeview.expandAll()

        # Reset layer list
        self.layer_list.clear()

        self.show_version_changes(version)
        self.update_canvas(self.diff_layers)

        return self.model.data(current_index, VersionsTableModel.VERSION)

    def closeEvent(self, event):
        self.save_splitters_state()
        QDialog.closeEvent(self, event)

    def save_splitters_state(self):
        settings = QSettings()
        settings.setValue("Mergin/VersionViewerSplitterSize", self.splitter.saveState())
        settings.setValue("Mergin/VersionViewerSplitterVericalSize", self.splitter_vertical.saveState())

    def set_splitters_state(self):
        settings = QSettings()
        state_vertical = settings.value("Mergin/VersionViewerSplitterVericalSize")
        if state_vertical:
            self.splitter_vertical.restoreState(state_vertical)
        else:
            self.splitter_vertical.setSizes([120, 200, 40])

        state = settings.value("Mergin/VersionViewerSplitterSize")
        if state:
            self.splitter.restoreState(state)
        else:
            height = max([self.map_canvas.minimumSizeHint().height(), self.attribute_table.minimumSizeHint().height()])
            self.splitter.setSizes([height, height])

    def set_mergin_client(self, mc):
        self.mc = mc

    def fetch_from_server(self):

        if self.fetcher and self.fetcher.isRunning():
            # Only fetching when previous is finshed
            return

        self.fetcher = VersionsFetcher(self.mc, self.mp.project_full_name(), self.model)
        self.fetcher.finished.connect(lambda versions: self.model.add_versions(versions))
        self.fetcher.start()

    def populate_details(self):
        self.edit_project_size.setText(bytes_to_human_size(self.version_details["project_size"]))
        self.edit_created.setText(format_datetime(self.version_details["created"]))
        self.edit_user_agent.setText(self.version_details["user_agent"])

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
        layers = self.collect_layers(checked)
        self.update_canvas(layers)

    def update_canvas(self, layers):
        self.map_canvas.setLayers(layers)
        if layers:
            self.map_canvas.setDestinationCrs(layers[0].crs())
            extent = layers[0].extent()
            d = min(extent.width(), extent.height())
            if d == 0:
                d = 1
            extent = extent.buffered(d * 0.07)
            self.map_canvas.setExtent(extent)
        self.map_canvas.refresh()

    def show_version_changes(self, version):
        self.diff_layers.clear()

        layers = make_version_changes_layers(QgsProject.instance().homePath(), version)
        for vl in layers:
            self.diff_layers.append(vl)
            icon = icon_for_layer(vl)

            self.layer_list.addItem(QListWidgetItem(icon, f"{vl.name()} ({vl.featureCount()})\n   2 updated"))

        if len(self.diff_layers) >= 1:
            self.toolbar.setEnabled(True)
            self.layer_list.setCurrentRow(0)
            self.stackedWidget.setCurrentIndex(0)
            self.tabWidget.setCurrentIndex(0)
            self.tabWidget.setTabEnabled(0, True)
        else:
            self.toolbar.setEnabled(False)
            self.stackedWidget.setCurrentIndex(1)
            self.tabWidget.setCurrentIndex(1)
            self.tabWidget.setTabEnabled(0, False)

    def collect_layers(self, checked):
        if checked:
            layers = iface.mapCanvas().layers()
        else:
            layers = []

        if self.current_diff:
            layers.insert(0, self.current_diff)

        return layers

    def diff_layer_changed(self, index):
        if index > len(self.diff_layers):
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
