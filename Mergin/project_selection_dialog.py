import os
import posixpath
from qgis.PyQt.QtWidgets import QDialog, QListWidget, QListWidgetItem, QListView, QAbstractItemDelegate, QStyle
from qgis.PyQt.QtCore import QSize, QSortFilterProxyModel, QStringListModel, Qt, QModelIndex, QRect, QMargins
from qgis.PyQt import uic
from qgis.PyQt.QtGui import QPixmap, QPainter, QStandardItemModel, QStandardItem, QFont, QFontMetrics

from .mergin.merginproject import MerginProject
from .utils import (
    icon_path,
    mergin_project_local_path,
)

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_select_project_dialog.ui")


class ProjectItemDelegate(QAbstractItemDelegate):
    def __init__(self):
        super(ProjectItemDelegate, self).__init__()

    def sizeHint(self, option: 'QStyleOptionViewItem', index: QModelIndex) -> QSize:
        fm = QFontMetrics(option.font)
        return QSize(150, fm.height() * 3 + fm.leading())

    def paint(self, painter: QPainter, option: 'QStyleOptionViewItem', index: QModelIndex) -> None:
        painter.save()
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect.marginsRemoved(QMargins(4, 4, 4, 4)), option.palette.highlight());

        nameFont = QFont(option.font)
        infoFont = QFont(option.font)
        nameFont.setWeight(QFont.Weight.Bold)
        fm = QFontMetrics(nameFont)
        nameRect = QRect(option.rect)
        nameRect.setLeft(nameRect.left() + fm.lineSpacing() // 2)
        nameRect.setTop(nameRect.top() + fm.lineSpacing() // 2)
        nameRect.setHeight(fm.lineSpacing())
        infoRect = fm.boundingRect(nameRect.left(), nameRect.bottom() + fm.leading(), nameRect.width(), 0, Qt.AlignLeading, index.data(Qt.UserRole + 1))
        infoRect.setTop(infoRect.bottom() - fm.lineSpacing())
        infoRect.setHeight(fm.lineSpacing())

        painter.drawRect(option.rect.marginsRemoved(QMargins(4, 4, 4, 4)))
        painter.setFont(nameFont)
        painter.drawText(nameRect, Qt.AlignLeading, index.data(Qt.DisplayRole))
        painter.setFont(infoFont)
        painter.drawText(infoRect, Qt.AlignLeading, index.data(Qt.UserRole + 1))
        painter.restore()


class ProjectSelectionDialog(QDialog):
    def __init__(self, projects):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self)

        self.ui.label_logo.setPixmap(QPixmap(icon_path("mm_icon_positive_no_padding.svg", True)))

        project_names = [w["name"] for w in projects]
        self.model = QStandardItemModel()
        for project in projects:
            item = QStandardItem(project["name"])

            project_name = posixpath.join(project["namespace"], project["name"])  # posix path for server API calls
            local_proj_path = mergin_project_local_path(project_name)
            if local_proj_path is None or not os.path.exists(local_proj_path):
                item.setData("Not downloaded", Qt.UserRole + 1)
            else:
                mp = MerginProject(local_proj_path)
                local_changes = mp.get_push_changes()
                if local_changes["added"] or local_changes["updated"]:
                    item.setData("Local changes waiting to be pushed", Qt.UserRole + 1)
                elif mp.metadata["version"] < project["version"]:  # todo: proper compare
                    item.setData("Update available", Qt.UserRole + 1)
                else:
                    item.setData("Up to date", Qt.UserRole + 1)


            self.model.appendRow(item)

        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.ui.project_list.setModel(self.proxy)
        delegate = ProjectItemDelegate()
        self.ui.project_list.setItemDelegate(delegate)
        self.ui.project_list.doubleClicked.connect(self.on_double_click)

        self.ui.line_edit.setShowSearchIcon(True)
        self.ui.line_edit.setVisible(len(projects) >= 5)
        self.ui.line_edit.textChanged.connect(self.proxy.setFilterFixedString)

    def on_double_click(self, index):
        self.workspace = self.proxy.data(index, Qt.EditRole)
        self.accept()

    def getWorkspace(self):
        return self.workspace
