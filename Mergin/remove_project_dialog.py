import os

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_remove_project_dialog.ui")


class RemoveProjectDialog(QDialog):
    def __init__(self, project_name, parent=None):
        QDialog.__init__(self, parent)
        self.ui = uic.loadUi(ui_file, self)

        self.project_name = project_name
        self.label.setText(
            f"This action will remove your MerginMaps project '<b>{self.project_name}</b>' from the server. "
            "This action cannot be undone.<br><br>"
            "In order to delete project, enter project name in the field below and click 'Yes'."
        )
        self.buttonBox.button(QDialogButtonBox.Yes).setEnabled(False)

        self.edit_project_name.textChanged.connect(self.project_name_changed)

    def project_name_changed(self, text):
        self.buttonBox.button(QDialogButtonBox.Yes).setEnabled(self.project_name == text)
