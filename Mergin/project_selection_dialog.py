import os
import posixpath
from enum import Enum, auto
from qgis.PyQt.QtWidgets import QDialog, QListView, QAbstractItemDelegate, QStyle
from qgis.PyQt.QtCore import (
    QSize,
    QSortFilterProxyModel,
    QAbstractListModel,
    Qt,
    QModelIndex,
    QRect,
    QMargins,
    pyqtSignal,
)
from qgis.PyQt import uic
from qgis.PyQt.QtGui import QPixmap, QPainter, QFont, QFontMetrics, QIcon

from .mergin.merginproject import MerginProject
from .utils import (
    icon_path,
    mergin_project_local_path,
    compare_versions,
)

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_select_project_dialog.ui")


class ProjectListView(QListView):

    currentIndexChanged = pyqtSignal(QModelIndex)

    def __init__(self, parent):
        super(ProjectListView, self).__init__(parent)

    def currentChanged(self, current, previous):
        super(ProjectListView, self).currentChanged(current, previous)
        self.currentIndexChanged.emit(current)

    def selectedIndex(self):
        try:
            return self.selectedIndexes()[0]
        except IndexError:
            return QModelIndex()


class SyncStatus(Enum):
    UP_TO_DATE = auto()
    NOT_DOWNLOADED = auto()
    LOCAL_CHANGES = auto()
    REMOTE_CHANGES = auto()


class ProjectsModel(QAbstractListModel):

    PROJECT = Qt.UserRole + 1
    NAME = Qt.UserRole + 2
    NAMESPACE = Qt.UserRole + 3
    STATUS = Qt.UserRole + 4
    LOCAL_DIRECTORY = Qt.UserRole + 5
    ICON = Qt.UserRole + 6

    def __init__(self, projects):
        super(ProjectsModel, self).__init__()
        self.projects = projects

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self.projects)

    def data(self, index, role):
        project = self.projects[index.row()]
        if role == ProjectsModel.PROJECT:
            return project
        if role == ProjectsModel.NAME:
            return project["name"]
        if role == ProjectsModel.NAMESPACE:
            return project["namespace"]
        if role == ProjectsModel.STATUS:
            status = self.status(project)
            if status == SyncStatus.NOT_DOWNLOADED:
                return "Not downloaded"
            elif status == SyncStatus.LOCAL_CHANGES:
                return "Local changes waiting to be pushed"
            elif status == SyncStatus.REMOTE_CHANGES:
                return "Update available"
            else:  # status == SyncStatus.UP_TO_DATE:
                return "Up to date"

        if role == ProjectsModel.LOCAL_DIRECTORY:
            return self.localProjectPath(project)
        if role == ProjectsModel.ICON:
            status = self.status(project)
            icon = ""
            if status == SyncStatus.NOT_DOWNLOADED:
                icon = "cloud-download.svg"
            elif status in (SyncStatus.LOCAL_CHANGES, SyncStatus.REMOTE_CHANGES):
                icon = "refresh.svg"
            return icon
        return project["name"]

    def localProjectPath(self, project):
        project_name = posixpath.join(project["namespace"], project["name"])  # posix path for server API calls
        return mergin_project_local_path(project_name)

    def status(self, project):
        local_proj_path = self.localProjectPath(project)
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

    def sizeHint(self, option: "QStyleOptionViewItem", index: QModelIndex) -> QSize:
        fm = QFontMetrics(option.font)
        return QSize(150, fm.height() * 3 + fm.leading())

    def paint(self, painter: QPainter, option: "QStyleOptionViewItem", index: QModelIndex) -> None:
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
        iconRect = iconRect.marginsRemoved(QMargins(10, 10, 10, 10))

        painter.save()
        if option.state & QStyle.State_Selected:
            painter.fillRect(borderRect, option.palette.highlight())
        painter.drawRect(borderRect)
        painter.setFont(nameFont)
        if self.show_namespace:
            text = '{} / {}'.format(index.data(ProjectsModel.NAMESPACE), index.data(ProjectsModel.NAME))
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

    def __init__(self, projects):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self, "Mergin")

        self.ui.label_logo.setPixmap(QPixmap(icon_path("mm_icon_positive_no_padding.svg", True)))

        self.model = ProjectsModel(projects)

        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.ui.project_list.setItemDelegate(ProjectItemDelegate())
        self.ui.project_list.setModel(self.proxy)
        self.ui.project_list.setCurrentIndex(self.proxy.index(0, 0))
        self.ui.project_list.doubleClicked.connect(self.on_double_click)
        self.ui.project_list.currentIndexChanged.connect(self.on_current_changed)

        self.ui.line_edit.setShowSearchIcon(True)
        self.ui.line_edit.textChanged.connect(self.proxy.setFilterFixedString)
        self.ui.line_edit.setFocus()

        self.ui.open_project_btn.setEnabled(bool(projects))
        self.ui.open_project_btn.clicked.connect(self.on_open_project_clicked)

        self.ui.new_project_btn.clicked.connect(self.on_new_project_clicked)
        self.ui.switch_workspace_label.linkActivated.connect(self.on_switch_workspace_clicked)

    def on_current_changed(self, index):
        self.ui.open_project_btn.setEnabled(index.isValid())

    def on_open_project_clicked(self):
        index = self.ui.project_list.selectedIndex()
        if not index.isValid():
            return

        project_path = self.proxy.data(index, ProjectsModel.LOCAL_DIRECTORY)
        if not project_path:
            project = self.proxy.data(index, ProjectsModel.PROJECT)
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
    def __init__(self, projects):
        super(PublicProjectSelectionDialog, self).__init__(projects)

        self.setWindowTitle("Explore public projects")
        self.ui.label.setText("Explore public community projects")

        self.ui.project_list.setItemDelegate(ProjectItemDelegate(show_namespace=True))
        self.enable_workspace_switching(False)
        self.enable_new_project(False)
