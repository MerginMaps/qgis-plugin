import os
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QApplication, QMessageBox
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QSettings, Qt

from .client import MerginClient

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'ui', 'ui_create_project.ui')


class CreateProjectDialog(QDialog):
    def __init__(self):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self)
        self.ui.input_validation.setText('')
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.project_name.textChanged.connect(self.text_changed)
        self.ui.project_dir.textChanged.connect(self.file_changed)
        self.ui.get_project_dir.clicked.connect(self.get_directory)

    def validate(self):
        if self.ui.project_name.text() and os.path.isdir(self.ui.project_dir.text()):
            self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(True)
        else:
            self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)

    def text_changed(self):
        msg = '' if self.ui.project_name.text() else '<font color=red>Please set up project name</font>'
        self.ui.input_validation.setText(msg)
        self.validate()

    def file_changed(self):
        msg = '' if os.path.isdir(self.ui.project_dir.text()) else '<font color=red>Please select correct directory</font>'
        self.ui.input_validation.setText(msg)
        self.validate()

    def get_directory(self):
        project_dir = QFileDialog.getExistingDirectory(None, "Open Directory", "", QFileDialog.ShowDirsOnly)
        if project_dir:
            self.ui.project_dir.setText(project_dir)
        else:
            self.ui.project_dir.setText('')

    def create_project(self):
        settings = QSettings()
        url = settings.value('Mergin/URL', 'https://public.cloudmergin.com')
        username = settings.value('Mergin/username', '')
        password = settings.value('Mergin/password', '')
        mc = MerginClient(url, username, password)
        project_name = self.ui.project_name.text()
        project_dir = self.ui.project_dir.text()

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            mc.create_project(project_name, project_dir, self.ui.is_public.isChecked())
            QApplication.restoreOverrideCursor()
            settings.setValue('Mergin/localProjects/{}/path'.format(project_name), project_dir)
            msg = "Mergin project created successfully"
            QMessageBox.information(None, 'Create Project', msg, QMessageBox.Close)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            settings.remove('Mergin/localProjects/{}/path'.format(project_name))
            msg = "Failed to complete Mergin project creation:\n{}\n\n" \
                  "There might be a broken project at server, please use web interface to fix the issue.".format(str(e))
            QMessageBox.critical(None, 'Create Project', msg, QMessageBox.Close)
