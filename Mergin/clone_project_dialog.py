import os
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QApplication, QMessageBox
from qgis.PyQt import uic

from .utils import is_valid_name

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_clone_project.ui")


class CloneProjectDialog(QDialog):
    def __init__(self, username, user_organisations=None):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.buttonBox.accepted.connect(self.accept_dialog)
        self.ui.projectNamespace.addItem(username)
        if user_organisations:
            self.ui.projectNamespace.addItems(
                [o for o in user_organisations if user_organisations[o] in ["admin", "owner"]]
            )
        self.ui.edit_project_name.textChanged.connect(self.text_changed)

        # these are the variables used by the caller
        self.project_name = None
        self.project_namespace = None
        self.invalid = False

    def text_changed(self):
        proj_name = self.ui.edit_project_name.text()
        if not is_valid_name(proj_name):
            self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
            if not self.invalid:
                QMessageBox.warning(self, "Clone Project", "Incorrect project name!")
            self.invalid = True
        else:
            self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(bool(proj_name))
            self.invalid = False

    def accept_dialog(self):
        self.project_name = self.ui.edit_project_name.text()
        self.project_namespace = self.ui.projectNamespace.currentText()

        self.accept()  # this will close the dialog and dlg.exec_() returns True
