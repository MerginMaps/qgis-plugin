import os
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QApplication, QMessageBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt import uic

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_clone_project.ui")


class CloneProjectDialog(QDialog):
    def __init__(self, user_info, workspaces=[]):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.buttonBox.accepted.connect(self.accept_dialog)
        if not workspaces:
            username = user_info["username"]
            user_organisations = user_info.get("organisations", [])
            self.ui.projectNamespace.addItem(username)
            for o in user_organisations:
                if user_organisations[o] in ["admin", "owner"]:
                    self.ui.projectNamespace.addItem(o, True)

        for ws in workspaces:
            is_writable = user_info["id"] in ws["writers"]
            self.ui.projectNamespace.addItem(ws["name"], is_writable)

        self.ui.projectNamespace.currentTextChanged.connect(self.workspace_changed)
        self.ui.edit_project_name.textChanged.connect(self.text_changed)

        # disable widgets if default workspace is read only
        self.workspace_changed()

        # these are the variables used by the caller
        self.project_name = None
        self.project_namespace = None

    def text_changed(self):
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(bool(self.ui.edit_project_name.text()))

    def workspace_changed(self):
        is_writable = self.ui.projectNamespace.currentData(Qt.UserRole)

        if is_writable:
            msg = ""
        else:
            msg = "You do not have write permissions for this workspace"
        self.ui.edit_project_name.setToolTip(msg)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setToolTip(msg)
        self.ui.edit_project_name.setEnabled(is_writable)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(is_writable and bool(self.ui.edit_project_name.text()))

    def accept_dialog(self):
        self.project_name = self.ui.edit_project_name.text()
        self.project_namespace = self.ui.projectNamespace.currentText()

        self.accept()  # this will close the dialog and dlg.exec_() returns True
