import os

from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QApplication, QMessageBox, QComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt import uic

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_clone_project.ui")


class CloneProjectDialog(QDialog):
    """Dialog for cloning remote projects. Allows selection of workspace/namespace and project name"""

    def __init__(self, user_info, default_workspace=None):
        """Create a dialog for cloning remote projects

        :param user_info: The user_info dictionary as returned from server
        :param default_workspace: Optionally, the name of the current workspace so it can be pre-selected in the list
        """
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.buttonBox.accepted.connect(self.accept_dialog)

        workspaces = user_info.get("workspaces", None)
        if workspaces is not None:
            for ws in workspaces:
                is_writable = ws.get("role", "owner") in ["owner", "admin", "writer"]
                self.ui.projectNamespace.addItem(ws["name"], is_writable)

        else:
            # This means server is old and uses namespaces
            self.ui.projectNamespaceLabel.setText("Owner")
            username = user_info["username"]
            user_organisations = user_info.get("organisations", [])
            self.ui.projectNamespace.addItem(username, True)
            for o in user_organisations:
                if user_organisations[o] in ["owner", "admin", "writer"]:
                    self.ui.projectNamespace.addItem(o, True)

        self.ui.projectNamespace.currentTextChanged.connect(self.workspace_changed)
        self.ui.edit_project_name.textChanged.connect(self.text_changed)

        # disable widgets if default workspace is read only
        self.workspace_changed()
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
            msg = "You do not have permissions to create a project in this workspace!"
        self.ui.edit_project_name.setToolTip(msg)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setToolTip(msg)
        self.ui.warningMessageLabel.setVisible(not is_writable)
        self.ui.warningMessageLabel.setText(msg)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(is_writable and bool(self.ui.edit_project_name.text()))

    def accept_dialog(self):
        self.project_name = self.ui.edit_project_name.text()
        self.project_namespace = self.ui.projectNamespace.currentText()

        self.accept()  # this will close the dialog and dlg.exec_() returns True
