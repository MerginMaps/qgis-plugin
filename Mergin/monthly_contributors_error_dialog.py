import os
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices

from .help import MerginHelp

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_monthly_contributors_error_dialog.ui")


class MonthlyContributorsErrorDialog(QDialog):
    def __init__(self, e, parent=None):
        QDialog.__init__(self, parent)
        self.ui = uic.loadUi(ui_file, self)

        self.server_response = e.server_response
        self.set_dialog_style()

        self.buttonBox.accepted.connect(self.open_upgrade_link)
        self.buttonBox.rejected.connect(self.reject)

    def set_dialog_style(self):
        upgrade_button = self.buttonBox.button(QDialogButtonBox.Ok)
        upgrade_button.setText("Upgrade")

        quota = self.server_response.get("contributors_quota", "#NA")
        quota_text = f"You've reached the maximum number of active monthly contributors ({quota}) for your current subscription."
        self.label.setText(quota_text)

    def open_upgrade_link(self):
        QDesktopServices.openUrl(QUrl(MerginHelp().mergin_subscription_link()))
        self.accept()
