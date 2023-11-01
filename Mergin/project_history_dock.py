import os
import math
import json
from urllib.error import URLError

from qgis.PyQt import uic
from qgis.PyQt.QtGui import QIcon, QStandardItemModel, QStandardItem, QFont, QFontMetrics
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal, QSortFilterProxyModel, QRect, QMargins, QSize
from qgis.PyQt.QtWidgets import QMenu, QAbstractItemDelegate, QMessageBox

from qgis.gui import QgsDockWidget
from qgis.core import Qgis
from qgis.utils import OverrideCursor, iface

from .diff_dialog import DiffViewerDialog
from .version_details_dialog import VersionDetailsDialog
from .utils import check_mergin_subdirs, icon_path, ClientError, is_versioned_file

from .mergin.merginproject import MerginProject
from .mergin.utils import int_version


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


class VersionItemDelegate(QAbstractItemDelegate):
    def __init__(self):
        super(VersionItemDelegate, self).__init__()

    def sizeHint(self, option, index):
        fm = QFontMetrics(option.font)
        return QSize(150, fm.height() * 2 + fm.leading())

    def paint(self, painter, option, index):
        font = QFont(option.font)
        fm = QFontMetrics(font)
        padding = fm.lineSpacing() // 2

        w = QRect(option.rect).width()
        dw = w // 5

        versionRect = QRect(option.rect)
        versionRect.setLeft(versionRect.left() + padding)
        versionRect.setTop(versionRect.top() + padding)
        versionRect.setRight(versionRect.left() + dw)
        versionRect.setHeight(fm.lineSpacing())

        authorRect = QRect(option.rect)
        authorRect.setLeft(versionRect.right() + padding)
        authorRect.setTop(authorRect.top() + padding)
        authorRect.setRight(authorRect.left() + dw * 2)
        authorRect.setHeight(fm.lineSpacing())

        dateRect = QRect(option.rect)
        dateRect.setLeft(authorRect.right() + padding)
        dateRect.setTop(dateRect.top() + padding)
        dateRect.setRight(dateRect.right() - padding)
        dateRect.setHeight(fm.lineSpacing())

        borderRect = QRect(option.rect.marginsRemoved(QMargins(4, 4, 4, 4)))

        painter.save()
        if option.state & QStyle.State_Selected:
            painter.fillRect(borderRect, option.palette.highlight())
        painter.drawRect(borderRect)

        elided_text = fm.elidedText(index.data(), Qt.ElideRight, versionRect.width())
        painter.drawText(versionRect, Qt.AlignLeading, elided_text)
        elided_text = fm.elidedText(index.data(VersionsModel.AUTHOR), Qt.ElideRight, authorRect.width())
        painter.drawText(authorRect, Qt.AlignLeading, elided_text)
        elided_text = fm.elidedText(index.data(VersionsModel.CREATED), Qt.ElideRight, dateRect.width())
        painter.drawText(dateRect, Qt.AlignLeading, elided_text)

        painter.restore()


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
        self.filter_btn.setEnabled(False)
        self.view_changes_btn.setIcon(QIcon(icon_path("file-diff.svg")))
        self.view_changes_btn.setEnabled(False)
        self.view_changes_btn.clicked.connect(self.show_changes)

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

        self.versions_list.setItemDelegate(VersionItemDelegate())
        self.versions_list.setModel(self.proxy)
        self.versions_list.verticalScrollBar().valueChanged.connect(self.on_scrollbar_changed)
        self.versions_list.customContextMenuRequested.connect(self.show_context_menu)

        selectionModel = self.versions_list.selectionModel()
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
        self.stackedWidget.setCurrentIndex(1)
        self.get_project_history()

    def set_project(self, project_path):
        self.project_path = project_path
        self.update_ui()

    def get_project_history(self):
        self.project_full_name = self.mp.project_full_name()
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

    def on_selection_changed(self, selected, deselected):
        if selected:
            index = selected.indexes()[0]
            self.view_changes_btn.setEnabled(index.isValid())
        else:
            self.view_changes_btn.setEnabled(False)

    def show_changes(self):
        if self.versions_list.selectedIndexes():
            index = self.versions_list.selectedIndexes()[0]
            source_index = self.proxy.mapToSource(index)
            item = self.model.itemFromIndex(source_index)
            version = item.data(VersionsModel.VERSION)
            self.view_changes(version)

    def show_context_menu(self, pos):
        index = self.versions_list.indexAt(pos)
        if not index.isValid():
            return

        source_index = self.proxy.mapToSource(index)
        item = self.model.itemFromIndex(source_index)
        version = item.data(VersionsModel.VERSION)

        menu = QMenu()
        view_details_action = menu.addAction("Version details")
        view_details_action.setIcon(QIcon(icon_path("file-description.svg")))
        view_details_action.triggered.connect(lambda: self.version_details(version))
        view_changes_action = menu.addAction("View changes")
        view_changes_action.setIcon(QIcon(icon_path("file-diff.svg")))
        view_changes_action.triggered.connect(lambda: self.view_changes(version))
        download_action = menu.addAction("Download this version")
        download_action.setIcon(QIcon(icon_path("cloud-download.svg")))
        download_action.triggered.connect(self.download_version)
        revert_action = menu.addAction("Revert to this version")
        revert_action.setIcon(QIcon(icon_path("arrow-back-up.svg")))
        revert_action.triggered.connect(self.revert_to_version)
        undo_action = menu.addAction("Undo changes in this version")
        undo_action.setIcon(QIcon(icon_path("arrow-back-up.svg")))
        undo_action.triggered.connect(self.undo_changes)

        menu.exec_(self.versions_list.mapToGlobal(pos))

    def version_details(self, version):
        """Shows version information with full view of added/updated/removed files"""
        with OverrideCursor(Qt.WaitCursor):
            info = self.mc.project_version_info(self.project_full_name, version)

        dlg = VersionDetailsDialog(info[0])
        dlg.exec_()

    def view_changes(self, version):
        """Shows comparison of changes in the version"""
        with OverrideCursor(Qt.WaitCursor):
            if not os.path.exists(os.path.join(self.project_path, ".mergin", ".cache", f"v{version}")):
                info = self.mc.project_info(self.project_full_name, version=f"v{version}")
                files = [f for f in info["files"] if is_versioned_file(f["path"])]
                if not files:
                    QMessageBox.information(
                        None, "Mergin", "This version does not contain changes in the project layers."
                    )
                    return

                has_history = any("diff" in f for f in files)
                if not has_history:
                    QMessageBox.information(
                        None, "Mergin", "This version does not contain changes in the project layers."
                    )
                    return

                for f in files:
                    if "diff" not in f:
                        continue
                    file_diffs = self.mc.download_file_diffs(self.project_path, f["path"], [f"v{version}"])
                    full_gpkg = self.mp.fpath_cache(f["path"], version=f"v{version}")
                    if not os.path.exists(full_gpkg):
                        self.mc.download_file(self.project_path, f["path"], full_gpkg, f"v{version}")

        dlg = DiffViewerDialog(version)
        dlg.exec_()

    def download_version(self):
        pass

    def revert_to_version(self):
        pass

    def undo_changes(self):
        pass
