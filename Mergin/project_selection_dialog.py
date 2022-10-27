import os
import posixpath
from qgis.PyQt.QtWidgets import QDialog, QListView, QAbstractItemDelegate, QStyle
from qgis.PyQt.QtCore import QSize, QSortFilterProxyModel, QAbstractListModel, Qt, QModelIndex, QRect, QMargins, pyqtSignal
from qgis.PyQt import uic
from qgis.PyQt.QtGui import QPixmap, QPainter, QStandardItemModel, QStandardItem, QFont, QFontMetrics

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


class ProjectsModel(QAbstractListModel):

    NAME = Qt.UserRole + 1
    NAMESPACE = Qt.UserRole + 2
    FULLNAME = Qt.UserRole + 3
    ISLOCAL = Qt.UserRole + 4
    FILEPATH = Qt.UserRole + 5
    VERSION = Qt.UserRole + 6
    STATUS = Qt.UserRole + 7
    DIRECTORY = Qt.UserRole + 8
    ICON = Qt.UserRole + 9

    def __init__(self, projects):
        super(ProjectsModel, self).__init__()
        self.projects = projects

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self.projects)

    # def index(self, row, column):
    #     return self.createIndex(row, 0)

    def data(self, index, role):
        project = self.projects[index.row()]
        if role == ProjectsModel.NAME:
            return project["name"]
        if role == ProjectsModel.NAMESPACE:
            return project["namespace"]
        if role == ProjectsModel.VERSION:
            return project["version"]
        if role == ProjectsModel.ISLOCAL:
            local_proj_path = self.locaProjectPath()
            return local_proj_path and os.path.exists(local_proj_path)
        if role == ProjectsModel.STATUS:
            return self.status(project)
        if role == ProjectsModel.DIRECTORY:
            return self.localProjectPath(project)
        if role == ProjectsModel.ICON:
            status = self.status(project)
            icon = ""
            if status == "Not downloaded":
                icon = "cloud-download.svg"
            elif status == "Local changes waiting to be pushed":
                icon = "refresh.svg"
            elif status == "Update available":
                icon = "refresh"
            return icon
        return project["name"]

    def localProjectPath(self, project):
        project_name = posixpath.join(project["namespace"], project["name"])  # posix path for server API calls
        return mergin_project_local_path(project_name)

    def status(self, project):
        project_name = posixpath.join(project["namespace"], project["name"])  # posix path for server API calls
        local_proj_path = mergin_project_local_path(project_name)
        if local_proj_path is None or not os.path.exists(local_proj_path):
            return "Not downloaded"

        mp = MerginProject(local_proj_path)
        local_changes = mp.get_push_changes()
        if local_changes["added"] or local_changes["updated"]:
            return "Local changes waiting to be pushed"
        elif compare_versions(project["version"], mp.metadata["version"]) > 0:
            return "Update available"
        else:
            return "Up to date"


class ProjectItemDelegate(QAbstractItemDelegate):
    def __init__(self):
        super(ProjectItemDelegate, self).__init__()

    def sizeHint(self, option: 'QStyleOptionViewItem', index: QModelIndex) -> QSize:
        fm = QFontMetrics(option.font)
        return QSize(150, fm.height() * 3 + fm.leading())

    def paint(self, painter: QPainter, option: 'QStyleOptionViewItem', index: QModelIndex) -> None:
        nameFont = QFont(option.font)
        fm = QFontMetrics(nameFont)
        padding = fm.lineSpacing() // 2
        nameFont.setWeight(QFont.Weight.Bold)


        nameRect = QRect(option.rect)
        nameRect.setLeft(nameRect.left() + padding)
        nameRect.setTop(nameRect.top() + padding)
        nameRect.setRight(nameRect.right() - 50 )
        nameRect.setHeight(fm.lineSpacing())
        infoRect = fm.boundingRect(nameRect.left(), nameRect.bottom() + fm.leading(), nameRect.width(), 0, Qt.AlignLeading, index.data(ProjectsModel.STATUS))
        infoRect.setTop(infoRect.bottom() - fm.lineSpacing())
        infoRect.setHeight(fm.lineSpacing())
        borderRect = QRect(option.rect.marginsRemoved(QMargins(4, 4, 4, 4)))
        iconRect = QRect(borderRect)
        iconRect.setLeft(nameRect.right())
        iconRect = iconRect.marginsRemoved(QMargins(10, 10, 10, 10))

        painter.save()
        if option.state & QStyle.State_Selected:
            painter.fillRect(borderRect, option.palette.highlight());
        painter.drawRect(borderRect)
        painter.setFont(nameFont)
        painter.drawText(nameRect, Qt.AlignLeading, index.data(Qt.DisplayRole))
        painter.setFont(option.font)
        painter.drawText(infoRect, Qt.AlignLeading, index.data(ProjectsModel.STATUS))
        painter.drawRect(iconRect)
        icon = index.data(ProjectsModel.ICON)
        if icon:
            painter.drawPixmap(iconRect, QPixmap(icon_path(icon)))
        painter.restore()


class ProjectSelectionDialog(QDialog):

    new_project_clicked = pyqtSignal()
    switch_workspace_clicked = pyqtSignal()
    open_project_clicked = pyqtSignal(str)

    def __init__(self, projects):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self, "Mergin")

        self.ui.label_logo.setPixmap(QPixmap(icon_path("mm_icon_positive_no_padding.svg", True)))

        self.model = ProjectsModel(projects)

        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.ui.project_list.setModel(self.proxy)
        delegate = ProjectItemDelegate()
        self.ui.project_list.setItemDelegate(delegate)
        self.ui.project_list.doubleClicked.connect(self.on_double_click)
        self.ui.project_list.currentIndexChanged.connect(self.on_current_changed)

        self.ui.line_edit.setShowSearchIcon(True)
        self.ui.line_edit.setVisible(len(projects) >= 5)
        self.ui.line_edit.textChanged.connect(self.proxy.setFilterFixedString)
        self.ui.line_edit.setFocus()

        self.ui.open_project_btn.setEnabled(False)
        self.ui.open_project_btn.clicked.connect(self.on_open_project_clicked)
        self.ui.new_project_btn.clicked.connect(self.on_new_project_clicked)
        self.ui.switch_workspace_label.linkActivated.connect(self.on_switch_workspace_clicked)

    def on_current_changed(self, index):
        project_path = self.proxy.data(index, ProjectsModel.DIRECTORY)
        self.ui.open_project_btn.setEnabled(bool(project_path))

    def on_open_project_clicked(self):
        index = self.ui.project_list.selectedIndex()
        if not index.isValid():
            return

        project_path = self.proxy.data(index, ProjectsModel.DIRECTORY)
        if not project_path:
            return

        self.close()
        self.open_project_clicked.emit(project_path)

    def on_new_project_clicked(self):
        self.close()
        self.new_project_clicked.emit()

    def on_switch_workspace_clicked(self):
        self.close()
        self.switch_workspace_clicked.emit()

    def on_double_click(self, index):
        self.on_open_project_clicked()

    def enable_workspace_switching(self, enable):
        self.ui.switch_workspace_label.setVisible(enable)

