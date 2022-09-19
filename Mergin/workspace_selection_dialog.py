import os
from qgis.PyQt.QtWidgets import QDialog
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
    def __init__(self, workspaces):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self)

        self.ui.label_logo.setPixmap(QPixmap(icon_path("mm_icon_positive_no_padding.svg", True)))
        self.workspace = None
        # TODO: use list view and filter model based on lineEdit
        self.ui.workspace_list.addItems(workspaces)
        self.ui.workspace_list.itemDoubleClicked.connect(self.accept)

    def accept(self):
        self.workspace = self.ui.workspace_list.selectedItems()[0].text()
        super().accept()

    def getWorkspace(self):
        return self.workspace
