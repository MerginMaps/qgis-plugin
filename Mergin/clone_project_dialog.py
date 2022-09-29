import os

from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QApplication, QMessageBox, QComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt import uic

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_clone_project.ui")


class CloneProjectDialog(QDialog):
    def __init__(self, user_info, workspaces=[], default_workspace=None):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.buttonBox.accepted.connect(self.accept_dialog)

        for ws in workspaces:
            try:
                # Check if server is ee offering per workspace permissions
                is_writable = user_info["id"] in ws["writers"]
                self.ui.projectNamespace.addItem(ws["name"], is_writable)
            except (KeyError, TypeError):
                # Server is ce, we'll ask for forgiveness instead of permission
                is_writable = True
                self.ui.projectNamespace.addItem(ws, is_writable)

        if not workspaces:
            # This means server is old and uses namespaces
            username = user_info["username"]
            user_organisations = user_info.get("organisations", [])
            self.ui.projectNamespace.addItem(username, True)
            self.ui.projectNamespaceLabel.setText("Owner")
            for o in user_organisations:
                if user_organisations[o] in ["admin", "owner"]:
                    self.ui.projectNamespace.addItem(o, True)

        self.ui.projectNamespace.currentTextChanged.connect(self.workspace_changed)
        self.ui.edit_project_name.textChanged.connect(self.text_changed)

        # disable widgets if default workspace is read only
        self.workspace_changed()
        if default_workspace:
            self.ui.projectNamespace.setCurrentText(default_workspace)

        # these are the variables used by the caller
        self.project_name = None
        self.project_namespace = None

    def text_changed(self):
        enabled = bool(self.ui.edit_project_name.text()) and not self.ui.warningMessageLabel.isVisible()
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(enabled)

    def workspace_changed(self):
        is_writable = bool(self.ui.projectNamespace.currentData(Qt.UserRole))
        if is_writable:
            msg = ""
        else:
            msg = "You do not have write permissions for this workspace"
        self.ui.edit_project_name.setToolTip(msg)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setToolTip(msg)
        self.ui.warningMessageLabel.setVisible(not is_writable)
        self.ui.warningMessageLabel.setText(msg)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(is_writable and bool(self.ui.edit_project_name.text()))

    def accept_dialog(self):
        self.project_name = self.ui.edit_project_name.text()
        self.project_namespace = self.ui.projectNamespace.currentText()

        self.accept()  # this will close the dialog and dlg.exec_() returns True
