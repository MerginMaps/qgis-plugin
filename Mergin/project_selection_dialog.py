import os
import posixpath
from enum import Enum, auto
from urllib.error import URLError
from qgis.PyQt.QtWidgets import QDialog, QAbstractItemDelegate, QStyle
from qgis.PyQt.QtCore import (
    QSize,
    QSortFilterProxyModel,
    Qt,
    QModelIndex,
    QRect,
    QMargins,
    pyqtSignal,
    QTimer,
)
from qgis.PyQt import uic
from qgis.PyQt.QtGui import QPixmap, QFont, QFontMetrics, QIcon, QStandardItem, QStandardItemModel
from qgis.core import (
    QgsApplication,
)
from .mergin.merginproject import MerginProject
from .utils import (
    icon_path,
    mergin_project_local_path,
    compare_versions,
    ClientError,
)

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_select_project_dialog.ui")


class SyncStatus(Enum):
    UP_TO_DATE = auto()
    NOT_DOWNLOADED = auto()
    LOCAL_CHANGES = auto()
    REMOTE_CHANGES = auto()


class ProjectsModel(QStandardItemModel):

    PROJECT = Qt.UserRole + 1
    NAME = Qt.UserRole + 2
    NAMESPACE = Qt.UserRole + 3
    STATUS = Qt.UserRole + 4
    LOCAL_DIRECTORY = Qt.UserRole + 5
    ICON = Qt.UserRole + 6

    def __init__(self, projects=None):
        super(ProjectsModel, self).__init__()
        if projects:
            self.appendProjects(projects)

    def appendProjects(self, projects):
        for item in self.createItems(projects):
            self.appendRow(item)

    @staticmethod
    def createItems(projects):
        items = []
        for project in projects:
            item = QStandardItem(project["name"])

            status = ProjectsModel.status(project)
            if status == SyncStatus.NOT_DOWNLOADED:
                status_string = "Not downloaded"
            elif status == SyncStatus.LOCAL_CHANGES:
                status_string = "Local changes waiting to be pushed"
            elif status == SyncStatus.REMOTE_CHANGES:
                status_string = "Update available"
            else:  # status == SyncStatus.UP_TO_DATE:
                status_string = "Up to date"

            icon = ""
            if status == SyncStatus.NOT_DOWNLOADED:
                icon = "cloud-download.svg"
            elif status in (SyncStatus.LOCAL_CHANGES, SyncStatus.REMOTE_CHANGES):
                icon = "refresh.svg"

            item.setData("{} / {}".format(project["namespace"], project["name"]), Qt.DisplayRole)
            item.setData(project, ProjectsModel.PROJECT)
            item.setData(project["name"], ProjectsModel.NAME)
            item.setData(project["namespace"], ProjectsModel.NAMESPACE)
            item.setData(status_string, ProjectsModel.STATUS)
            item.setData(ProjectsModel.localProjectPath(project), ProjectsModel.LOCAL_DIRECTORY)
            item.setData(icon, ProjectsModel.ICON)
            items.append(item)
        return items

    @staticmethod
    def localProjectPath(project):
        project_name = posixpath.join(project["namespace"], project["name"])  # posix path for server API calls
        return mergin_project_local_path(project_name)

    @staticmethod
    def status(project):
        local_proj_path = ProjectsModel.localProjectPath(project)
        if local_proj_path is None or not os.path.exists(local_proj_path):
            return SyncStatus.NOT_DOWNLOADED

        mp = MerginProject(local_proj_path)
        local_changes = mp.get_push_changes()
        if local_changes["added"] or local_changes["updated"]:
            return SyncStatus.LOCAL_CHANGES
        elif compare_versions(project["version"], mp.metadata["version"]) > 0:
            return SyncStatus.REMOTE_CHANGES
        else:
            return SyncStatus.UP_TO_DATE


class ProjectItemDelegate(QAbstractItemDelegate):
    def __init__(self, show_namespace=False):
        super(ProjectItemDelegate, self).__init__()
        self.show_namespace = show_namespace

    def sizeHint(self, option, index):
        fm = QFontMetrics(option.font)
        return QSize(150, fm.height() * 3 + fm.leading())

    def paint(self, painter, option, index):
        nameFont = QFont(option.font)
        fm = QFontMetrics(nameFont)
        padding = fm.lineSpacing() // 2
        nameFont.setWeight(QFont.Weight.Bold)

        nameRect = QRect(option.rect)
        nameRect.setLeft(nameRect.left() + padding)
        nameRect.setTop(nameRect.top() + padding)
        nameRect.setRight(nameRect.right() - 50)
        nameRect.setHeight(fm.lineSpacing())
        infoRect = fm.boundingRect(
            nameRect.left(),
            nameRect.bottom() + fm.leading(),
            nameRect.width(),
            0,
            Qt.AlignLeading,
            index.data(ProjectsModel.STATUS),
        )
        infoRect.setTop(infoRect.bottom() - fm.lineSpacing())
        infoRect.setHeight(fm.lineSpacing())
        borderRect = QRect(option.rect.marginsRemoved(QMargins(4, 4, 4, 4)))
        iconRect = QRect(borderRect)
        iconRect.setLeft(nameRect.right())
        iconRect = iconRect.marginsRemoved(QMargins(12, 12, 12, 12))

        painter.save()
        if option.state & QStyle.State_Selected:
            painter.fillRect(borderRect, option.palette.highlight())
        painter.drawRect(borderRect)
        painter.setFont(nameFont)
        if self.show_namespace:
            text = index.data(Qt.DisplayRole)
        else:
            text = index.data(ProjectsModel.NAME)
        painter.drawText(nameRect, Qt.AlignLeading, text)
        painter.setFont(option.font)
        painter.drawText(infoRect, Qt.AlignLeading, index.data(ProjectsModel.STATUS))
        icon = index.data(ProjectsModel.ICON)
        if icon:
            icon = QIcon(icon_path(icon))
            icon.paint(painter, iconRect)
        painter.restore()


class ProjectSelectionDialog(QDialog):

    new_project_clicked = pyqtSignal()
    switch_workspace_clicked = pyqtSignal()
    open_project_clicked = pyqtSignal(str)
    download_project_clicked = pyqtSignal(dict)

    def __init__(self, mc, workspace_name):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self, "Mergin")

        self.ui.label_logo.setPixmap(QPixmap(icon_path("mm_logo.svg", False)))

        self.mc = mc
        self.current_workspace_name = workspace_name

        self.fetched_projects_number = 0
        self.total_projects_number = 0
        self.need_to_fetch_more = False
        self.text_change_timer = QTimer()
        self.text_change_timer.setSingleShot(True)
        self.text_change_timer.setInterval(500)
        self.text_change_timer.timeout.connect(self.fetch_from_server)

        self.request_page = 1
        self.model = ProjectsModel()
        self.ui.project_list.setItemDelegate(ProjectItemDelegate())
        self.ui.project_list.setModel(self.model)
        selectionModel = self.ui.project_list.selectionModel()
        selectionModel.selectionChanged.connect(self.on_selection_changed)
        self.ui.project_list.doubleClicked.connect(self.on_double_click)
        self.ui.project_list.verticalScrollBar().valueChanged.connect(self.on_scrollbar_changed)

        self.ui.line_edit.setShowSearchIcon(True)
        self.ui.line_edit.textChanged.connect(self.on_text_changed)
        self.ui.line_edit.setFocus()

        self.ui.open_project_btn.clicked.connect(self.on_open_project_clicked)

        self.ui.new_project_btn.clicked.connect(self.on_new_project_clicked)
        self.ui.switch_workspace_label.linkActivated.connect(self.on_switch_workspace_clicked)

        self.text_change_timer.start()

    def on_scrollbar_changed(self, val):
        if not self.need_to_fetch_more:
            return

        if self.ui.project_list.verticalScrollBar().maximum() <= val:
            self.fetch_from_server()

    def on_text_changed(self, text):
        self.text_change_timer.start()
        self.request_page = 1

    def fetch_from_server(self):
        name = self.ui.line_edit.text()
        try:
            QgsApplication.instance().setOverrideCursor(Qt.WaitCursor)
            projects = self.mc.paginated_projects_list(
                flag=None,
                namespace=self.current_workspace_name,
                order_params="namespace_asc,name_asc",
                name=name,
                page=self.request_page,
            )
            if self.request_page == 1:
                self.model.clear()
                self.fetched_projects_number = 0
            self.model.appendProjects(projects["projects"])

            self.fetched_projects_number += len(projects["projects"])
            self.total_projects_number = projects["count"]
            if self.total_projects_number > self.fetched_projects_number:
                self.request_page += 1
                self.need_to_fetch_more = True
            else:
                self.need_to_fetch_more = False

        except (URLError, ClientError) as e:
            return
        finally:
            QgsApplication.instance().restoreOverrideCursor()

    def on_selection_changed(self, selected, deselected):
        try:
            index = selected.indexes()[0]
        except IndexError:
            index = QModelIndex()
        self.ui.open_project_btn.setEnabled(index.isValid())

    def on_open_project_clicked(self):
        try:
            index = self.ui.project_list.selectedIndexes()[0]
        except IndexError:
            index = QModelIndex()
        if not index.isValid():
            return

        project_path = self.model.data(index, ProjectsModel.LOCAL_DIRECTORY)
        if not project_path:
            project = self.model.data(index, ProjectsModel.PROJECT)
            self.close()
            self.download_project_clicked.emit(project)
            return

        self.close()
        self.open_project_clicked.emit(project_path)

    def on_double_click(self, index):
        self.on_open_project_clicked()

    def on_new_project_clicked(self):
        self.close()
        self.new_project_clicked.emit()

    def on_switch_workspace_clicked(self):
        self.close()
        self.switch_workspace_clicked.emit()

    def enable_workspace_switching(self, enable):
        self.ui.switch_workspace_label.setVisible(enable)

    def enable_new_project(self, enable):
        self.ui.new_project_btn.setVisible(enable)


class PublicProjectSelectionDialog(ProjectSelectionDialog):
    def __init__(self, mc):
        super(PublicProjectSelectionDialog, self).__init__(mc, workspace_name="")

        self.setWindowTitle("Explore public projects")
        self.ui.label.setText("Explore public community projects")

        self.ui.project_list.setItemDelegate(ProjectItemDelegate(show_namespace=True))
        self.enable_workspace_switching(False)
        self.enable_new_project(False)
