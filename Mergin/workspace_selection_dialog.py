import os
from qgis.PyQt.QtWidgets import QDialog
from qgis.PyQt.QtCore import QSortFilterProxyModel, QStringListModel, Qt, pyqtSignal, QModelIndex
from qgis.PyQt import uic
from qgis.PyQt.QtGui import QPixmap

from .utils import (
    icon_path,
)

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_select_workspace_dialog.ui")


class WorkspaceSelectionDialog(QDialog):

    manage_workspaces_clicked = pyqtSignal(str)

    def __init__(self, workspaces):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self)

        self.ui.label_logo.setPixmap(QPixmap(icon_path("mm_logo.svg", False)))

        self.workspace = None

        workspaces_names = [w["name"] for w in workspaces]
        self.model = QStringListModel(workspaces_names)

        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.ui.workspace_list.setModel(self.proxy)
        self.ui.workspace_list.doubleClicked.connect(self.on_double_click)

        self.ui.line_edit.setShowSearchIcon(True)
        self.ui.line_edit.setVisible(len(workspaces) >= 5)
        self.ui.line_edit.textChanged.connect(self.proxy.setFilterFixedString)

        self.ui.select_workspace_btn.clicked.connect(self.on_select_workspace_clicked)
        self.ui.manage_workspaces_label.linkActivated.connect(self.on_manage_workspaces_clicked)

    def on_select_workspace_clicked(self):
        self.accept()

    def on_double_click(self, index):
        self.accept()

    def on_manage_workspaces_clicked(self):
        self.manage_workspaces_clicked.emit("/workspaces")

    def getWorkspace(self):
        return self.workspace

    def accept(self):
        try:
            index = self.ui.workspace_list.selectedIndexes()[0]
        except IndexError:
            index = QModelIndex()
        if not index.isValid():
            return

        self.workspace = self.proxy.data(index, Qt.DisplayRole)
        QDialog.accept(self)
