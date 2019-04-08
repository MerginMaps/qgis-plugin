
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
        last_url = settings.value('Mergin/URL', '')
        self.ui.merginURL.setText(last_url)

    def run(self):
        settings = QSettings()
        if bool(self.exec_()):
            url = self.ui.merginURL.text()
            settings.setValue("Mergin/URL", url)
        else:
            last_url = settings.value('Mergin/URL', '')
            self.ui.merginURL.setText(last_url)
