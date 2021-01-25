import os
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QMessageBox
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QSettings

from qgis.core import QgsProject
from qgis.utils import iface

from .utils import create_basic_qgis_project, find_qgis_files

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_create_project.ui")


class CreateProjectDialog(QDialog):
    def __init__(self, username, user_organisations=None):
        QDialog.__init__(self)
        self.iface = iface
        self.ui = uic.loadUi(ui_file, self)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.buttonBox.accepted.connect(self.accept_dialog)
        self.ui.project_namespace_cbo.addItem(username)
        if user_organisations:
            self.ui.project_namespace_cbo.addItems(
                [o for o in user_organisations if user_organisations[o] in ["admin", "owner"]]
            )
        self.ui.edit_project_name.textChanged.connect(self.text_changed)
        self.ui.btn_get_project_dir.clicked.connect(self.get_directory)
        self.ui.rad_project_dir.toggled.connect(self.toggle_select_dir)
        self.toggle_select_dir()

        # these are the variables used by the caller
        self.project_namespace = None
        self.project_name = None
        self.project_dir = None
        self.is_public = None

    def text_changed(self):
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(bool(self.ui.edit_project_name.text()))

    def toggle_select_dir(self):
        self.ui.btn_get_project_dir.setEnabled(self.ui.rad_project_dir.isChecked())
        self.ui.edit_project_dir.setEnabled(self.ui.rad_project_dir.isChecked())

    def get_directory(self):
        project_dir = QFileDialog.getExistingDirectory(None, "Open Directory", "", QFileDialog.ShowDirsOnly)
        if project_dir:
            self.ui.edit_project_dir.setText(project_dir)
        else:
            self.ui.edit_project_dir.setText("")

    def accept_dialog(self):
        """ Called when user pressed OK """
        settings = QSettings()
        project_name = self.ui.edit_project_name.text()
        project_dir = None
        if self.rad_cur_project.isChecked():
            project_dir = QgsProject.instance().absolutePath()
        elif self.ui.rad_project_dir.isChecked():
            project_dir = self.ui.edit_project_dir.text()
        elif self.ui.rad_blank_project.isChecked():
            project_path = create_basic_qgis_project(project_name=project_name)
            if project_path is not None:
                self.iface.addProject(project_path)
                # workaround to set proper extent
                self.iface.mapCanvas().zoomToFullExtent()
                project_dir = QgsProject.instance().absolutePath()

        username = settings.value("Mergin/username", "")
        if username == "":
            QMessageBox.warning(self, "Create Project", "Username is not stored. Please save configuration again.")
            return

        if project_dir and not os.path.exists(project_dir):
            QMessageBox.warning(self, "Create Project", "Project directory does not exist.")
            return

        if project_dir and ".mergin" in os.listdir(project_dir):
            QMessageBox.warning(
                self,
                "Create Project",
                "The selected directory seems to be already used "
                "for a Mergin project.\n\n(There is already .mergin sub-directory.)",
            )
            return

        if project_dir and len(find_qgis_files(project_dir)) > 1:
            msg = f"Current project directory:\n{project_dir}\ncontains multiple QGIS projects."\
                  "Remove some and try again with a single project in the directory."
            QMessageBox.warning(self, "Create Project", msg)
            return

        self.project_name = project_name
        self.project_dir = project_dir
        self.project_namespace = self.ui.project_namespace_cbo.currentText()
        self.is_public = self.ui.chk_is_public.isChecked()

        self.accept()  # this will close the dialog and dlg.exec_() returns True
