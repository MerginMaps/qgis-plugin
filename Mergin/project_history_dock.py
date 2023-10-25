import os

from qgis.PyQt import uic
from qgis.PyQt.QtGui import QIcon

from qgis.gui import QgsDockWidget

from .mergin.merginproject import MerginProject
from .utils import check_mergin_subdirs, icon_path

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_project_history_dock.ui")


class ProjectHistoryDockWidget(QgsDockWidget):
    def __init__(self, mc):
        QgsDockWidget.__init__(self)
        self.ui = uic.loadUi(ui_file, self)

        self.filter_btn.setIcon(QIcon(icon_path("filter.svg")))
        self.view_changes_btn.setIcon(QIcon(icon_path("file-diff.svg")))

        self.mc = mc
        self.mp = None
        self.project_path = None

        self.update_ui()

    def update_ui(self):
        if self.project_path is None:
            self.info_label.setText("Current project is not saved. Project history is not available.")
            self.stackedWidget.setCurrentIndex(0)
            return

        if not check_mergin_subdirs(self.project_path):
            self.info_label.setText("Current project is not a Mergin project. Project history is not available.")
            self.stackedWidget.setCurrentIndex(0)
            return

        self.mp = MerginProject(self.project_path)
        self.stackedWidget.setCurrentIndex(1)
        # TODO: load project history

    def set_project(self, project_path):
        self.project_path = project_path
        self.update_ui()
