import os
import math
import json
from urllib.error import URLError
from collections import deque

from PyQt5.QtCore import QObject
from qgis.PyQt import uic
from qgis.PyQt.QtGui import QIcon, QFont
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal, QSortFilterProxyModel, QAbstractItemModel, QModelIndex, QAbstractTableModel
from qgis.PyQt.QtWidgets import QMenu, QMessageBox

from qgis.gui import QgsDockWidget
from qgis.core import Qgis, QgsMessageLog
from qgis.utils import iface

from .diff_dialog import DiffViewerDialog
from .version_details_dialog import VersionDetailsDialog

from .utils import (
    ClientError, 
    mergin_project_local_path, 
    check_mergin_subdirs,
    contextual_date,
    icon_path,
    )

from .mergin.merginproject import MerginProject
from .mergin.utils import int_version, is_versioned_file

from .mergin import MerginClient

class VersionsTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)

        #Keep ordered
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
        #Fetch while we are not the the first version
        return self.oldest_version() == None  or self.oldest_version() >= 1

    def fetchMore(self, parent: QModelIndex) -> None:
        pass
        #emit
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

    def __init__(self, mc : MerginClient , project_name, model: VersionsTableModel, is_sync=False):
        super(VersionsFetcher, self).__init__()
        self.mc = mc
        self.project_name = project_name
        self.model = model

        self.is_sync = is_sync

        self.per_page = 50 #server limit

    def run(self):

        if (not self.is_sync):
            versions = self.fetch_previous()
        else:
            versions = self.fetch_sync_history()

        self.finished.emit(versions)
    
    def fetch_previous(self):

        if len(self.model.versions) == 0:
            #initial fetch 
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
    
        #determine latest 
        info = self.mc.project_info(self.project_name)

        latest_server = int_version(info["version"])
        since = self.model.latest_version()

        versions = self.mc.project_versions(self.project_name, since=since, to=latest_server)
        versions.pop() #Remove the last as we already have it
        versions.reverse()

        return versions


ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_project_history_dock.ui")

class ProjectHistoryDockWidget(QgsDockWidget):
    def __init__(self, mc):
        QgsDockWidget.__init__(self)
        self.ui = uic.loadUi(ui_file, self)

        self.mc = mc
        self.mp = None

        self.project_path = mergin_project_local_path()
        
        self.fetcher = None
        self.diff_downloader = None



        self.model = VersionsTableModel()
        # self.model.versions.extend([{"name" : "blabla"},{"name" : "blabla2"}])
        self.versions_tree.setModel(self.model)
        self.versions_tree.verticalScrollBar().valueChanged.connect(self.on_scrollbar_changed)
        
        self.versions_tree.customContextMenuRequested.connect(self.show_context_menu)

        self.view_changes_btn.clicked.connect(self.model.append)

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
        usage = self.mc.workspace_usage(ws_id)
        if not usage["view_history"]["allowed"]:
            self.info_label.setText("The workspace does not allow to view project history.")
            self.stackedWidget.setCurrentIndex(0)
            return

        self.stackedWidget.setCurrentIndex(1)


        self.model.current_version = self.mp.version()
        self.fetch_from_server()
        
    def fetch_from_server(self):

        if self.fetcher and self.fetcher.isRunning():
            # Only fetching when previous is finshed
            return

        self.fetcher = VersionsFetcher(self.mc, self.mp.project_full_name(), self.model)
        self.fetcher.finished.connect(lambda versions: self.model.add_versions(versions))
        self.fetcher.start()
    
    def fetch_sync_server(self):

        if self.fetcher and self.fetcher.isRunning():
            # Only fetching when previous is finshed
            self.fetcher.requestInterruption()

        self.fetcher = VersionsFetcher(self.mc, self.mp.project_full_name(), self.model, is_sync=True)
        self.fetcher.finished.connect(lambda versions: self.model.prepend_versions(versions))
        self.fetcher.start()
    

    def on_scrollbar_changed(self, value):
        if self.ui.versions_tree.verticalScrollBar().maximum() <= value:
            self.fetch_from_server()

    

    def show_context_menu(self, pos):
        """Shows context menu in the project history dock"""
        index = self.versions_tree.indexAt(pos)
        if not index.isValid():
            return

        item = self.model.item_from_index(index)
        version_name = item["name"]
        version = int_version(item["name"])

        menu = QMenu()
        view_details_action = menu.addAction("Version details")
        view_details_action.setIcon(QIcon(icon_path("file-description.svg")))
        view_details_action.triggered.connect(lambda: self.version_details(version_name))
        view_changes_action = menu.addAction("View changes")
        view_changes_action.setIcon(QIcon(icon_path("file-diff.svg")))
        view_changes_action.triggered.connect(lambda: self.view_changes(version))


        menu.exec_(self.versions_tree.mapToGlobal(pos))



    def version_details(self, version):
        """Shows version information with full view of added/updated/removed files"""

        data = self.mc.project_version_info(self.mp.project_id(), version)
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
        if dlg.diff_layers:
            dlg.exec_()
        else:
            QMessageBox.information(None, "Mergin", "No changes to the current project layers for this version.")

    def set_mergin_client(self, mc):
        self.mc = mc
        
    def on_qgis_project_changed(self):
        self.model.clear()
        self.project_path = mergin_project_local_path()
        self.update_ui()