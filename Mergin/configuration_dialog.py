
import os
from qgis.PyQt.QtWidgets import QDialog
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QSettings

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'ui', 'ui_config.ui')


class ConfigurationDialog(QDialog):
    def __init__(self):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self)

        settings = QSettings()
        last_url = settings.value('Mergin/URL', 'https://public.cloudmergin.com')
        self.ui.merginURL.setText(last_url)

    def writeSettings(self):
        settings = QSettings()
        url = self.ui.merginURL.text()
        settings.setValue("Mergin/URL", url)
