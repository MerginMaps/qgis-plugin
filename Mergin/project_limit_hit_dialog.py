import os
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_project_limit_hit_dialog.ui")

class ProjectLimitHitDialog(QDialog):
    def __init__(self, e, parent=None):
        QDialog.__init__(self, parent)
        self.ui = uic.loadUi(ui_file, self)
        
        quota = e.server_response.get('projects_quota', 'N/A')
        plan = e.server_response.get('plan', 'N/A')
        self.planQuota_label.setText(str(quota))
        self.planName_label.setText(str(plan))
        
        self.cancel_btn.clicked.connect(self.reject)
        self.upgrade_plan_btn.clicked.connect(self.open_upgrade_link)
        
    def open_upgrade_link(self):
        QDesktopServices.openUrl(QUrl("https://www.merginmaps.com/pricing"))
        self.accept()