import os

from qgis.PyQt import uic
from qgis.PyQt.QtCore import QSettings, Qt, QSize
from qgis.PyQt.QtWidgets import QApplication, QWizard, QFileDialog

from qgis.core import QgsProject
from qgis.utils import iface

from .utils import create_basic_qgis_project, find_qgis_files

base_dir = os.path.dirname(__file__)
uicls_init_page, basecls_init_page = uic.loadUiType(os.path.join(base_dir, "ui", "ui_new_proj_init_page.ui"))
uicls_local_path_page, basecls_local_path_page = uic.loadUiType(os.path.join(base_dir, "ui", "ui_get_path_page.ui"))
uicls_proj_settings, basecls_proj_settings = uic.loadUiType(os.path.join(base_dir, "ui", "ui_project_settings_page.ui"))

INIT_PAGE = 0
SAVE_PAGE = 1
LOCATE_PAGE = 2
SETTINGS_PAGE = 3
PACK_PAGE = 4

MIN_MERGIN_PROJ_PATH_LEN = 4


class InitPage(uicls_init_page, basecls_init_page):
    """Initial wizard page with Mergin project sources to choose."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.parent = parent
        self.btns_page = {
            self.basic_proj_btn: SAVE_PAGE,
            self.cur_proj_no_pack_btn: LOCATE_PAGE,
            # self.cur_proj_pack_btn: SAVE_PAGE,
        }
        for btn in self.btns_page.keys():
            btn.setAutoExclusive(True)
            btn.clicked.connect(self.selection_changed)
        self.hidden_ledit.hide()
        self.registerField("create_from*", self.hidden_ledit)

    def selection_changed(self):
        self.hidden_ledit.setText("Selection done!")

    def nextId(self):
        """Decide about the next page based on checkable buttons."""
        next_id = INIT_PAGE
        for btn in self.btns_page.keys():
            if btn.isChecked():
                next_id = self.btns_page[btn]
                break
        # make sure current project is saved, if not, open save page instead of locate
        proj_path = QgsProject.instance().absoluteFilePath()
        if next_id == LOCATE_PAGE and not proj_path:
            next_id = SAVE_PAGE
        return next_id


class ChoosePathPage(uicls_local_path_page, basecls_local_path_page):
    """Page for getting local path for saving new Mergin project."""

    def __init__(self, question=None, existing=None, file_filter=None, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.parent = parent
        self.file_filter = "QGIS projects (*.qgz *.qgs *.QGZ *.QGS)" if file_filter is None else file_filter
        self.registerField("project_path*", self.path_ledit)
        self.file_path = existing
        self.dir_path = None
        settings = QSettings()
        self.last_dir = settings.value("Mergin/lastUsedDownloadDir", "")
        self.path_ledit.setReadOnly(True)

        if question is None:
            question = "Choose path"
        self.question_label.setText(question)

        if not existing:
            self.browse_btn.clicked.connect(self.browse_save)
        else:
            self.path_ledit.setText(existing)
            self.check_directory()
            self.browse_btn.clicked.connect(self.browse_locate)

        self.path_ledit.textChanged.connect(self.check_directory)

    def nextId(self):
        return SETTINGS_PAGE

    def browse(self, existing=True):
        """Browse for new or existing QGIS project files."""
        user_path = self.path_ledit.text()
        self.last_dir = user_path if user_path else self.last_dir
        if existing:
            self.file_path, filters = QFileDialog.getOpenFileName(
                None, "Choose your project file", self.last_dir, self.file_filter
            )
        else:
            self.file_path, filters = QFileDialog.getSaveFileName(
                None, "Save project as", self.last_dir, self.file_filter
            )
            if self.file_path and not (self.file_path.endswith(".qgs") or self.file_path.endswith(".qgz")):
                self.file_path += ".qgz"

        if self.file_path:
            self.path_ledit.setText(self.file_path)
            self.dir_path = os.path.dirname(self.file_path)
            settings = QSettings()
            settings.setValue("Mergin/lastUsedDownloadDir", self.dir_path)
            self.last_dir = self.dir_path
        else:
            self.dir_path = None
        self.check_directory()

    def browse_save(self):
        """Browse for file path where to save project."""
        self.browse(existing=False)

    def browse_locate(self):
        """Browse for existing QGIS project file."""
        self.browse()

    def check_directory(self):
        """Check if the path is not already a mergin project and has at most a single QGIS project file."""
        cur_text = self.path_ledit.text()
        if not cur_text:
            return
        warn = ""
        cur_dir = cur_text if os.path.isdir(cur_text) else os.path.dirname(cur_text)
        if len(cur_dir) < MIN_MERGIN_PROJ_PATH_LEN:
            return

        if not os.path.exists(cur_dir):
            self.warning_edit.document().setPlainText("The path does not exist")
            return

        self.warning_edit.document().setPlainText("Checking the directory...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        qgis_files = find_qgis_files(cur_dir)
        QApplication.processEvents()
        QApplication.restoreOverrideCursor()

        qgis_files_nr = len(qgis_files)
        if self.file_path not in qgis_files:
            qgis_files_nr += 1
        if ".mergin" in os.listdir(cur_dir):
            warn = "Warning: The selected directory seems to be already used for a Mergin project."
        if not warn and qgis_files_nr > 1:
            warn = "Warning: Chosen directory would contain more that one QGIS project."

        if warn:
            warn += "\n\nConsider another directory for saving the project."
        else:
            warn = "Path correct. Click Next button."

        self.warning_edit.document().setPlainText(warn)


class ProjectSettingsPage(uicls_proj_settings, basecls_proj_settings):
    """Wizard page for getting project namespace, name and visibility."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.parent = parent
        self.registerField("project_name*", self.project_name_ledit)
        self.populate_namespace_cbo()

    def nextId(self):
        return -1

    def populate_namespace_cbo(self):
        self.project_owner_cbo.addItem(self.parent.username)
        if self.parent.user_organisations:
            self.project_owner_cbo.addItems(
                [o for o in self.parent.user_organisations if self.parent.user_organisations[o] in ["admin", "owner"]]
            )


class NewMerginProjectWizard(QWizard):
    """Wizard for creating new Mergin project."""

    def __init__(self, username, user_organisations=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.settings = QSettings()
        self.setWindowTitle("Create new Mergin project")
        self.setWizardStyle(QWizard.ClassicStyle)
        self.username = username
        self.user_organisations = user_organisations

        self.init_page = InitPage(self)
        self.setPage(INIT_PAGE, self.init_page)

        q_save = "Where to save the project on your computer?"
        self.save_proj_path_page = ChoosePathPage(question=q_save)
        self.setPage(SAVE_PAGE, self.save_proj_path_page)

        q_loc = "Where is your project located?"
        current_proj_path = QgsProject.instance().absoluteFilePath()
        self.locate_proj_page = ChoosePathPage(question=q_loc, existing=current_proj_path)
        self.setPage(LOCATE_PAGE, self.locate_proj_page)

        self.settings_page = ProjectSettingsPage(parent=self)
        self.setPage(SETTINGS_PAGE, self.settings_page)

        self.cancel_btn = self.button(QWizard.CancelButton)
        self.cancel_btn.clicked.connect(self.cancel_wizard)

        self.currentIdChanged.connect(self.page_change)

        # these are the variables used by the caller
        self.project_namespace = None
        self.project_name = None
        self.project_file = None
        self.project_dir = None
        self.is_public = None
        self.package_data = None

    def page_change(self):
        """Run when page has changed."""

    def get_project_paths(self):
        """Get QGIS project path and dir variables."""
        if self.save_proj_path_page.file_path is not None:
            self.project_file = self.save_proj_path_page.file_path
        elif self.locate_proj_page.file_path is not None:
            self.project_file = self.locate_proj_page.file_path
        else:
            # should not happen
            raise
        self.project_dir = os.path.dirname(self.project_file)

    def accept(self):
        self.get_project_paths()
        self.project_namespace = self.settings_page.project_owner_cbo.currentText()
        self.project_name = self.settings_page.project_name_ledit.text()
        self.is_public = self.settings_page.public_chbox.isChecked()

        if self.init_page.basic_proj_btn.isChecked():
            self.project_file = create_basic_qgis_project(
                project_path=self.project_file, project_name=self.project_name)
            if self.project_file is not None:
                self.iface.addProject(self.project_file)
                # workaround to set proper extent
                self.iface.mapCanvas().zoomToFullExtent()

        self.project_dir = QgsProject.instance().absolutePath()
        super().accept()

    def cancel_wizard(self):
        self.reject()
