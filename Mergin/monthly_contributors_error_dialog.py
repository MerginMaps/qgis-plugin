import os
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_monthly_contributors_error_dialog.ui")


class MonthlyContributorsErrorDialog(QDialog):
    def __init__(self, e, parent=None):
        QDialog.__init__(self, parent)
        self.ui = uic.loadUi(ui_file, self)

        self.server_response = e.server_response
        self.set_dialog_style()

        self.cancel_btn.clicked.connect(self.reject)
        self.upgrade_plan_btn.clicked.connect(self.open_upgrade_link)

    def set_dialog_style(self):
        quota = self.server_response.get("contributors_quota", "#NA")
        quota_text = f"{quota}/{quota}"

        self.plan_quota_progress_bar.setFormat(quota_text)
        self.plan_quota_progress_bar.setStyleSheet(
            """
            QProgressBar {
                border: none;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: rgb(0, 76, 69);
            }
        """
        )

    def open_upgrade_link(self):
        QDesktopServices.openUrl(QUrl("https://www.merginmaps.com/pricing"))
        self.accept()
