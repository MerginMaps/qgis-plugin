import os
import math
import json
from urllib.error import URLError

from qgis.PyQt import uic
from qgis.PyQt.QtGui import QIcon, QStandardItemModel, QStandardItem
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal, QSortFilterProxyModel
from qgis.PyQt.QtWidgets import QMenu

from qgis.gui import QgsDockWidget

from .mergin.merginproject import MerginProject
from .mergin.utils import int_version

from .utils import check_mergin_subdirs, icon_path, ClientError

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_project_history_dock.ui")


class VersionsModel(QStandardItemModel):
    VERSION = Qt.UserRole + 1
    AUTHOR = Qt.UserRole + 2
    CREATED = Qt.UserRole + 3

    def __init__(self, versions=None):
        super(VersionsModel, self).__init__()
        if versions:
            self.appendVersions(versions)

    def appendVersions(self, versions):
        for item in self.createItems(versions):
            self.appendRow(item)

    @staticmethod
    def createItems(versions):
        items = []
        for version in versions:
            item = QStandardItem(version["name"])
            item.setData(int_version(version["name"]), VersionsModel.VERSION)
            item.setData(version["author"], VersionsModel.AUTHOR)
            item.setData(version["created"], VersionsModel.CREATED)
            items.append(item)
        return items


class VersionsFetcher(QThread):
    """
    Class to handle fetching paginated list of project versions in background worker thread
    """

    finished = pyqtSignal(list)

    def __init__(self, mc, project_name, page):
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

    def isFetchingNextPage(self):
        return self.page > 1

    def run(self):
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


class ProjectHistoryDockWidget(QgsDockWidget):
    def __init__(self, mc):
        QgsDockWidget.__init__(self)
        self.ui = uic.loadUi(ui_file, self)

        self.filter_btn.setIcon(QIcon(icon_path("filter.svg")))
        self.view_changes_btn.setIcon(QIcon(icon_path("file-diff.svg")))

        self.mc = mc
        self.mp = None
        self.project_path = None
        self.project_full_name = None
        self.last_project_version = None

        self.need_to_fetch_next_page = False
        self.request_page = None
        self.fetcher = None

        self.model = VersionsModel()
        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(VersionsModel.VERSION)

        self.versions_list.setModel(self.proxy)
        self.versions_list.verticalScrollBar().valueChanged.connect(self.on_scrollbar_changed)
        self.versions_list.customContextMenuRequested.connect(self.show_context_menu)

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
        self.stackedWidget.setCurrentIndex(1)
        self.get_project_history()

    def set_project(self, project_path):
        self.project_path = project_path
        self.update_ui()

    def get_project_history(self):
        self.project_full_name = self.mp.metadata["name"]
        info = self.mc.project_info(self.project_full_name)
        self.last_project_version = info["version"]

        self.fetch_from_server()

    def on_scrollbar_changed(self, value):
        if not self.need_to_fetch_next_page:
            return

        if self.versions_list.verticalScrollBar().maximum() <= value:
            self.fetch_from_server(fetch_next_page=True)

    def fetch_from_server(self, fetch_next_page=False):
        if not fetch_next_page:
            self.request_page = math.ceil(int_version(self.last_project_version) / 100)
            self.versions_list.clearSelection()
            self.versions_list.scrollToTop()
            self.model.clear()

        if self.fetcher and self.fetcher.isRunning():
            if fetch_next_page and self.fetcher.isFetchingNextPage():
                # We only want one fetch_next_page request at a time
                return
            else:
                # Let's replace the existing request with the new one
                self.fetcher.requestInterruption()

        self.fetcher = VersionsFetcher(self.mc, self.project_full_name, self.request_page)
        self.fetcher.finished.connect(self.handle_server_response)
        self.fetcher.start()

    def handle_server_response(self, versions):
        try:
            last_fetched_version = versions[-1]["name"]
            if last_fetched_version != "v1":
                self.request_page = self.request_page - 1
                self.need_to_fetch_next_page = True
            else:
                self.need_to_fetch_next_page = False

            self.model.appendVersions(versions)
        except KeyError:
            pass

    def show_context_menu(self, pos):
        index = self.versions_list.indexAt(pos)
        print("index", index.row(), index.column())

        if not index.isValid():
            return

        source_index = self.proxy.mapToSource(index)
        print("source index", source_index.row(), source_index.column())
        item = self.model.itemFromIndex(source_index)
        print(item.text())

        menu = QMenu()
        view_details_action = menu.addAction("Version details")
        view_details_action.setIcon(QIcon(icon_path("file-description.svg")))
        #view_details_action.triggered.connect(self.version_details)
        view_changes_action = menu.addAction("View changes")
        view_changes_action.setIcon(QIcon(icon_path("file-diff.svg")))
        #view_changes_action.triggered.connect(self.version_details)
        download_action = menu.addAction("Download this version")
        download_action.setIcon(QIcon(icon_path("cloud-download.svg")))
        #download_action.triggered.connect(self.version_details)
        revert_action = menu.addAction("Revert to this version")
        revert_action.setIcon(QIcon(icon_path("arrow-back-up.svg")))
        #revert_action.triggered.connect(self.version_details)
        undo_action = menu.addAction("Undo changes in this version")
        undo_action.setIcon(QIcon(icon_path("arrow-back-up.svg")))
        #undo_action.triggered.connect(self.version_details)

        menu.exec_(self.versions_tree.mapToGlobal(pos))
