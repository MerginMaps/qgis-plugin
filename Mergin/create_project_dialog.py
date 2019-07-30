import os
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QApplication, QMessageBox
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QSettings, Qt
from .utils import create_mergin_client, get_mergin_auth

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'ui', 'ui_create_project.ui')


class CreateProjectDialog(QDialog):
    def __init__(self):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self)
        self.ui.input_validation.setText('')
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.project_name.textChanged.connect(self.text_changed)
        self.ui.get_project_dir.clicked.connect(self.get_directory)

    def text_changed(self):
        if self.ui.project_name.text():
            self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(True)
            msg = ''
        else:
            self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
            msg = '<font color=red>Please set up project name</font>'
        self.ui.input_validation.setText(msg)

    def get_directory(self):
        project_dir = QFileDialog.getExistingDirectory(None, "Open Directory", "", QFileDialog.ShowDirsOnly)
        if project_dir:
            self.ui.project_dir.setText(project_dir)
        else:
            self.ui.project_dir.setText('')

    def _return_failure(self, reason):
        QApplication.restoreOverrideCursor()
        msg = "Failed to complete Mergin project creation.\n" + reason
        QMessageBox.critical(None, 'Create Project', msg, QMessageBox.Close)

    def create_project(self):
        settings = QSettings()
        mc = create_mergin_client()
        project_name = self.ui.project_name.text()
        project_dir = self.ui.project_dir.text()
        _, username, _ = get_mergin_auth()
        QApplication.setOverrideCursor(Qt.WaitCursor)

        if project_dir and '.mergin' in os.listdir(project_dir):
            self._return_failure("Selected directory is already assigned to mergin project.")
            return

        try:
            mc.create_project(project_name, project_dir, self.ui.is_public.isChecked())
            QApplication.restoreOverrideCursor()
            settings.setValue('Mergin/localProjects/{}/path'.format(os.path.join(username, project_name)), project_dir)
            msg = "Mergin project created successfully"
            QMessageBox.information(None, 'Create Project', msg, QMessageBox.Close)
        except Exception as e:
            settings.remove('Mergin/localProjects/{}/path'.format(project_name))
            msg = str(e) + "\n\nThere might be a broken project at server, please use web interface to fix the issue."
            self._return_failure(msg)
