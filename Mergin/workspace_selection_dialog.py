import os
from qgis.PyQt.QtWidgets import QDialog, QListWidget, QListWidgetItem, QListView
from qgis.PyQt.QtCore import QSize, QSortFilterProxyModel, QStringListModel, Qt
from qgis.PyQt import uic
from qgis.PyQt.QtGui import QPixmap

try:
    from .mergin.client import MerginClient, ClientError, LoginError
except ImportError:
    import sys

    this_dir = os.path.dirname(os.path.realpath(__file__))
    path = os.path.join(this_dir, "mergin_client.whl")
    sys.path.append(path)
    from mergin.client import MerginClient, ClientError, LoginError

from .utils import (
    icon_path,
)

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_select_workspace_dialog.ui")


class WorkspaceSelectionDialog(QDialog):
    def __init__(self, plugin):
        QDialog.__init__(self)
        self.plugin = plugin
        workspaces = plugin.server_workspaces
        self.ui = uic.loadUi(ui_file, self)

        self.ui.label_logo.setPixmap(QPixmap(icon_path("mm_icon_positive_no_padding.svg", True)))
        self.workspace = None

        self.model = QStringListModel(workspaces)
        for i in range(self.model.rowCount()):
            idx = self.model.index(i, 0)
            self.model.setData(idx, QSize(100, 50), Qt.SizeHintRole)
            # wtf this has no effect?

        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.ui.workspace_list.setModel(self.proxy)
        self.ui.workspace_list.doubleClicked.connect(self.on_double_click)

        self.ui.line_edit.setShowSearchIcon(True)
        self.ui.line_edit.setVisible(len(workspaces) >= 5)
        self.ui.line_edit.textChanged.connect(self.proxy.setFilterFixedString)

        self.ui.manage_workspaces.clicked.connect(self.plugin.open_configured_url)

    def on_double_click(self, index):
        self.workspace = self.proxy.data(index, Qt.EditRole)
        self.accept()

    def getWorkspace(self):
        return self.workspace
