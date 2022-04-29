import json
import os
from qgis.PyQt import uic
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QFileDialog
from qgis.core import QgsProject
from qgis.gui import QgsOptionsWidgetFactory, QgsOptionsPageWidget
from .utils import icon_path, mergin_project_local_path

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'ui', 'ui_project_config.ui')
ProjectConfigUiWidget, _ = uic.loadUiType(ui_file)


class MerginProjectConfigFactory(QgsOptionsWidgetFactory):
    def __init__(self):
        QgsOptionsWidgetFactory.__init__(self)

    def icon(self):
        return QIcon(icon_path("icon.png", fa_icon=False))

    def title(self):
        return "Mergin"

    def createWidget(self, parent):
        return ProjectConfigWidget(parent)


class ProjectConfigWidget(ProjectConfigUiWidget, QgsOptionsPageWidget):
    def __init__(self, parent=None):
        QgsOptionsPageWidget.__init__(self, parent)
        self.setupUi(self)

        self.cmb_photo_quality.addItem("Original", 0)
        self.cmb_photo_quality.addItem("High (approx. 2-4 Mb)", 1)
        self.cmb_photo_quality.addItem("Medium (approx. 1-2 Mb)", 2)
        self.cmb_photo_quality.addItem("Low (approx. 0.5 Mb)", 3)

        quality, ok = QgsProject.instance().readEntry("Mergin", "PhotoQuality")
        idx = self.cmb_photo_quality.findData(quality) if ok else 0
        self.cmb_photo_quality.setCurrentIndex(idx if idx > 0 else 0)

        self.local_project_dir = mergin_project_local_path()

        if self.local_project_dir:
            self.config_file = os.path.join(self.local_project_dir, "mergin-config.json")
            self.load_config_file()
            self.btn_get_sync_dir.clicked.connect(self.get_sync_dir)
        else:
            self.selective_sync_group.setEnabled(False)
        self.photo_quality_groupbox.hide()

    def get_sync_dir(self):
        abs_path = QFileDialog.getExistingDirectory(None, "Select directory", self.local_project_dir, QFileDialog.ShowDirsOnly)
        if self.local_project_dir not in abs_path:
            return
        dir_path = abs_path.replace(self.local_project_dir, "").lstrip("/")
        self.edit_sync_dir.setText(dir_path)

    def load_config_file(self):
        if not self.local_project_dir or not os.path.exists(self.config_file):
            return

        with open(self.config_file, "r") as f:
            config = json.load(f)
            self.edit_sync_dir.setText(config["input-selective-sync-dir"])
            self.chk_sync_enabled.setChecked(config["input-selective-sync"])

    def save_config_file(self):
        if not self.local_project_dir:
            return

        if os.path.exists(self.config_file):
            with open(self.config_file, "r") as f:
                config = json.load(f)
        else:
            config = {}

        config["input-selective-sync"] = self.chk_sync_enabled.isChecked()
        config["input-selective-sync-dir"] = self.edit_sync_dir.text()

        with open(self.config_file, "w") as f:
            json.dump(config, f, indent=2)

    def apply(self):
        QgsProject.instance().writeEntry("Mergin", "PhotoQuality", self.cmb_photo_quality.currentData())
        self.save_config_file()
