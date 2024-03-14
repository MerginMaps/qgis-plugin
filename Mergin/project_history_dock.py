import os
import math
import json
from urllib.error import URLError

from qgis.PyQt import uic
from qgis.PyQt.QtGui import QIcon, QFont
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal, QSortFilterProxyModel, QAbstractItemModel, QModelIndex
from qgis.PyQt.QtWidgets import QMenu, QMessageBox

from qgis.gui import QgsDockWidget
from qgis.core import Qgis
from qgis.utils import iface

from .diff_dialog import DiffViewerDialog
from .version_details_dialog import VersionDetailsDialog
from .utils import check_mergin_subdirs, icon_path, ClientError, is_versioned_file, contextual_date, format_datetime

from .mergin.merginproject import MerginProject
from .mergin.utils import int_version


ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_project_history_dock.ui")


class Node:
    def __init__(self):
        self.parent = None
        self.children = list()

    def add_child_node(self, node):
        if node is None:
            return

        node.parent = self
        self.children.append(node)

    def delete_children(self):
        self.children.clear()


class VersionsModel(QAbstractItemModel):
    VERSION = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root_node = Node()

        self.current_version = None
        self.versions = []

    def clear(self):
        self.beginResetModel()
        self.root_node.delete_children()
        self.versions.clear()
        self.rebuild()
        self.endResetModel()

    def add_versions(self, versions):
        self.versions.extend(versions)
        self.rebuild()

    def rebuild(self):
        self.beginResetModel()
        self.root_node.delete_children()
        for v in self.versions:
            version_node = Node()
            self.root_node.add_child_node(version_node)
        self.endResetModel()

    def set_current_version(self, version):
        self.current_version = version

    def index2node(self, index):
        if not index.isValid():
            return self.root_node

        return index.internalPointer()

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        idx = index.row()
        if role == Qt.DisplayRole:
            if index.column() == 0:
                return self.versions[idx]["name"]
            elif index.column() == 1:
                return self.versions[idx]["author"]
            elif index.column() == 2:
                return contextual_date(self.versions[idx]["created"])
            else:
                return None
        elif role == Qt.ToolTipRole:
            if index.column() == 2:
                return format_datetime(self.versions[idx]["created"])
        elif role == Qt.FontRole:
            if self.versions[idx]["name"] == self.current_version:
                font = QFont()
                font.setBold(True)
                return font
        elif role == VersionsModel.VERSION:
            return int_version(self.versions[idx]["name"])
        else:
            return None

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if section == 0:
                return "Version"
            elif section == 1:
                return "Author"
            elif section == 2:
                return "Created"
            else:
                return None
        return None

    def rowCount(self, parent=QModelIndex()):
        node = self.index2node(parent)
        if node is None:
            return 0

        return len(node.children)

    def columnCount(self, parent=QModelIndex()):
        return 3

    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        node = self.index2node(parent)
        if node is None:
            return QModelIndex()

        return self.createIndex(row, column, node.children[row])

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()

        node = self.index2node(index)
        if node is not None:
            return self.index_of_parent_tree_node(node.parent)
        else:
            return QModelIndex()

    def index_of_parent_tree_node(self, parent_node):
        grand_parent_node = parent_node.parent
        if grand_parent_node is None:
            return QModelIndex()

        row = grand_parent_node.children.index(parent_node)
        return self.createIndex(row, 0, parent_node)

    def item_from_index(self, index):
        return self.versions[index.row()]


class VersionsFetcher(QThread):
    """
    Class to handle fetching paginated list of project versions in background worker thread
    """

    finished = pyqtSignal(list)

    def __init__(self, mc, project_name, page, since=None, to=None):
        """
        VersionsFetcher constructor

        :param mc: MerginClient instance
        :param project_name: namespace to filter by
        :param page: page to fetch
        """
        super(VersionsFetcher, self).__init__()
        self.mc = mc
        self.project_name = project_name
        self.page = page
        self.since = since
        self.to = to

    def isFetchingNextPage(self):
        return self.page > 1

    def run(self):
        if self.since and self.to:
            self.fetch_missed_versions()
        else:
            self.fetch_page()

    def fetch_page(self):
        try:
            params = {"page": self.page, "per_page": 100, "descending": True}
            resp = self.mc.get("/v1/project/versions/paginated/{}".format(self.project_name), params)
            json_resp = json.load(resp)
            versions = json_resp["versions"]
            if self.isInterruptionRequested():
                return
            self.finished.emit(versions)
        except (URLError, ClientError) as e:
            return

    def fetch_missed_versions(self):
        try:
            versions = self.mc.project_versions(self.project_name, self.since, self.to)
            if self.isInterruptionRequested():
                return
            # first item corresponds to the local project version and is not needed
            self.finished.emit(versions[1:])
        except (URLError, ClientError) as e:
            return


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


class ProjectHistoryDockWidget(QgsDockWidget):
    def __init__(self, mc):
        QgsDockWidget.__init__(self)
        self.ui = uic.loadUi(ui_file, self)

        self.view_changes_btn.setIcon(QIcon(icon_path("file-diff.svg")))
        self.view_changes_btn.setEnabled(False)
        self.view_changes_btn.clicked.connect(self.show_changes)

        self.mc = mc
        self.mp = None
        self.project_path = None
        self.server_project_version = None
        self.local_project_version = None
        self.last_seen_version = None

        self.need_to_fetch_next_page = False
        self.request_page = None
        self.versions_fetcher = None
        self.diff_downloader = None

        self.model = VersionsModel()
        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(VersionsModel.VERSION)
        self.proxy.sort(0, Qt.DescendingOrder)
        self.versions_tree.setModel(self.proxy)
        self.versions_tree.verticalScrollBar().valueChanged.connect(self.on_scrollbar_changed)
        self.versions_tree.customContextMenuRequested.connect(self.show_context_menu)

        selectionModel = self.versions_tree.selectionModel()
        selectionModel.selectionChanged.connect(self.on_selection_changed)

        self.update_ui()

    def set_mergin_client(self, mc):
        self.mc = mc
        self.update_ui()

    def update_ui(self):
        if self.mc is None:
            self.info_label.setText("Plugin is not configured.")
            self.stackedWidget.setCurrentIndex(0)
            return

        if self.project_path is None:
            self.info_label.setText("Current project is not saved. Project history is not available.")
            self.stackedWidget.setCurrentIndex(0)
            return

        if not check_mergin_subdirs(self.project_path):
            self.info_label.setText("Current project is not a Mergin project. Project history is not available.")
            self.stackedWidget.setCurrentIndex(0)
            return

        self.mp = MerginProject(self.project_path)
        self.local_project_version = self.mp.version()
        try:
            ws_id = self.mp.workspace_id()
        except ClientError as e:
            self.info_label.setText(str(e))
            self.stackedWidget.setCurrentIndex(0)
            return

        # check if user has permissions
        resp = self.mc.get(f"/v1/workspace/{ws_id}/usage")
        usage = json.load(resp)
        if not usage["view_history"]["allowed"]:
            self.info_label.setText("The workspace does not allow to view project history.")
            self.stackedWidget.setCurrentIndex(0)
            return

        self.stackedWidget.setCurrentIndex(1)
        self.get_project_history()

    def set_project(self, project_path):
        if self.project_path is None or self.project_path != project_path:
            self.project_path = project_path
            self.model.clear()
            self.update_ui()

    def get_project_history(self):
        """Fetch project history from the server starting from the latest server
        version of the project.
        """
        if not self.isVisible():
            return

        info = self.mc.project_info(self.mp.project_full_name())
        self.server_project_version = info["version"]

        if self.model.rowCount() == 0:
            self.load_history()

        if self.last_seen_version and self.server_project_version > self.last_seen_version:
            self.update_history()

    def on_scrollbar_changed(self, value):
        if not self.need_to_fetch_next_page:
            return

        if self.versions_tree.verticalScrollBar().maximum() <= value:
            self.load_history(fetch_next_page=True)

    def load_history(self, fetch_next_page=False):
        """Loads project history via paginated requests"""
        if not fetch_next_page:
            self.request_page = math.ceil(int_version(self.server_project_version) / 100)
            self.versions_tree.clearSelection()
            self.versions_tree.scrollToTop()
            self.model.clear()

        if self.versions_fetcher and self.versions_fetcher.isRunning():
            if fetch_next_page and self.versions_fetcher.isFetchingNextPage():
                # We only want one fetch_next_page request at a time
                return
            else:
                # Let's replace the existing request with the new one
                self.versions_fetcher.requestInterruption()

        self.versions_fetcher = VersionsFetcher(self.mc, self.mp.project_full_name(), self.request_page)
        self.versions_fetcher.finished.connect(self.handle_server_response)
        self.versions_fetcher.start()

    def update_history(self):
        """Fetches information about project versions after sync"""
        if self.versions_fetcher and self.versions_fetcher.isRunning():
            self.versions_fetcher.requestInterruption()

        self.versions_fetcher = VersionsFetcher(
            self.mc, self.mp.project_full_name(), 1, self.last_seen_version, self.server_project_version
        )
        self.versions_fetcher.finished.connect(lambda versions: self.handle_server_response(versions, False))
        self.versions_fetcher.start()

    def handle_server_response(self, versions, check_next_page=True):
        try:
            if self.last_seen_version is None:
                self.last_seen_version = versions[0]["name"]
            else:
                if self.last_seen_version < versions[0]["name"]:
                    self.last_seen_version = versions[0]["name"]

            if check_next_page:
                last_fetched_version = versions[-1]["name"]
                if last_fetched_version != "v1":
                    self.request_page = self.request_page - 1
                    self.need_to_fetch_next_page = True
                else:
                    self.need_to_fetch_next_page = False

            self.mp = MerginProject(self.project_path)
            self.model.add_versions(versions)
            self.model.set_current_version(self.mp.version())
        except KeyError:
            pass

    def on_selection_changed(self, selected, deselected):
        if selected:
            index = selected.indexes()[0]
            self.view_changes_btn.setEnabled(index.isValid())
        else:
            self.view_changes_btn.setEnabled(False)

    def show_changes(self):
        """Shows a Diff Viewer dialog with changes made in the currently selected version"""
        if self.versions_tree.selectedIndexes():
            index = self.versions_tree.selectedIndexes()[0]
            source_index = self.proxy.mapToSource(index)
            item = self.model.item_from_index(source_index)
            self.view_changes(int_version(item["name"]))

    def show_context_menu(self, pos):
        """Shows context menu in the project history dock"""
        index = self.versions_tree.indexAt(pos)
        if not index.isValid():
            return

        source_index = self.proxy.mapToSource(index)
        item = self.model.item_from_index(source_index)
        version = int_version(item["name"])

        menu = QMenu()
        view_details_action = menu.addAction("Version details")
        view_details_action.setIcon(QIcon(icon_path("file-description.svg")))
        view_details_action.triggered.connect(lambda: self.version_details(item))
        view_changes_action = menu.addAction("View changes")
        view_changes_action.setIcon(QIcon(icon_path("file-diff.svg")))
        view_changes_action.triggered.connect(lambda: self.view_changes(version))
        # download_action = menu.addAction("Download this version")
        # download_action.setIcon(QIcon(icon_path("cloud-download.svg")))
        # download_action.triggered.connect(self.download_version)
        # revert_action = menu.addAction("Revert to this version")
        # revert_action.setIcon(QIcon(icon_path("arrow-back-up.svg")))
        # revert_action.triggered.connect(self.revert_to_version)
        # undo_action = menu.addAction("Undo changes in this version")
        # undo_action.setIcon(QIcon(icon_path("arrow-back-up.svg")))
        # undo_action.triggered.connect(self.undo_changes)

        menu.exec_(self.versions_tree.mapToGlobal(pos))

    def version_details(self, data):
        """Shows version information with full view of added/updated/removed files"""
        dlg = VersionDetailsDialog(data)
        dlg.exec_()

    def view_changes(self, version):
        """Initiates download of changesets for the given version if they are not present
        in the cache. Otherwise use cached changesets to show diff viewer dialog.
        """
        if not os.path.exists(os.path.join(self.project_path, ".mergin", ".cache", f"v{version}")):
            if self.diff_downloader and self.diff_downloader.isRunning():
                self.diff_downloader.requestInterruption()

            self.diff_downloader = ChangesetsDownloader(self.mc, self.mp, version)
            self.diff_downloader.finished.connect(lambda msg: self.show_diff_viewer(version, msg))
            self.diff_downloader.start()
        else:
            self.show_diff_viewer(version)

    def show_diff_viewer(self, version, msg=""):
        """Shows a Diff Viewer dialog with changes made in the specific version.
        If msg is not empty string, show message box and returns.
        """
        if msg != "":
            QMessageBox.information(None, "Mergin", msg)
            return

        dlg = DiffViewerDialog(version)
        dlg.exec_()

    def download_version(self):
        """Download project files at the specific version"""
        pass

    def revert_to_version(self):
        """Revert project to the specific version"""
        pass

    def undo_changes(self):
        """Undo changes from the specific version"""
        pass
