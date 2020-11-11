import os
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QApplication, QMessageBox
from qgis.PyQt import uic

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'ui', 'ui_create_project.ui')


class ProjectDialog(QDialog):
    def __init__(self, title, username, user_organisations=None):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.buttonBox.accepted.connect(self.accept_dialog)
        self.ui.projectNamescape.addItem(username)
        if user_organisations:
            self.ui.projectNamescape.addItems([o for o in user_organisations
                                               if user_organisations[o] in ['admin', 'owner', 'writer']])
        self.ui.edit_project_name.textChanged.connect(self.text_changed)

        self.ui.setWindowTitle(title)
        self.ui.chk_is_public.setVisible(False)
        self.ui.btn_get_project_dir.setVisible(False)
        self.ui.edit_project_dir.setVisible(False)
        self.ui.rad_blank_project.setVisible(False)
        self.ui.rad_project_dir.setVisible(False)

        # these are the variables used by the caller
        self.project_name = None
        self.project_namespace = None

    def text_changed(self):
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(bool(self.ui.edit_project_name.text()))

    def accept_dialog(self):
        if not self.ui.edit_project_name.text():
            QMessageBox.warning(self, "Copy Project", "Missing name for a copied project")
            return

        self.project_name = self.ui.edit_project_name.text()
        self.project_namespace = self.ui.projectNamescape.currentText()

        self.accept()  # this will close the dialog and dlg.exec_() returns True
