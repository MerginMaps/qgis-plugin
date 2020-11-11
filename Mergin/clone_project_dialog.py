import os
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QApplication, QMessageBox
from qgis.PyQt import uic

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'ui', 'ui_clone_project.ui')


class CloneProjectDialog(QDialog):
    def __init__(self, username, user_organisations=None):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.buttonBox.accepted.connect(self.accept_dialog)
        self.ui.projectNamespace.addItem(username)
        if user_organisations:
            self.ui.projectNamespace.addItems([o for o in user_organisations
                                               if user_organisations[o] in ['admin', 'owner']])
        self.ui.edit_project_name.textChanged.connect(self.text_changed)

        # these are the variables used by the caller
        self.project_name = None
        self.project_namespace = None

    def text_changed(self):
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(bool(self.ui.edit_project_name.text()))

    def accept_dialog(self):
        self.project_name = self.ui.edit_project_name.text()
        self.project_namespace = self.ui.projectNamespace.currentText()

        self.accept()  # this will close the dialog and dlg.exec_() returns True
