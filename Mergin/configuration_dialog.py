import os
from qgis.PyQt.QtWidgets import QDialog, QApplication
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QSettings
from urllib.error import URLError

try:
    from .mergin.client import MerginClient, ClientError
except ImportError:
    import sys
    this_dir = os.path.dirname(os.path.realpath(__file__))
    path = os.path.join(this_dir, 'mergin_client.whl')
    sys.path.append(path)
    from mergin.client import MerginClient, ClientError

from .utils import get_mergin_auth, set_mergin_auth

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'ui', 'ui_config.ui')


class ConfigurationDialog(QDialog):
    def __init__(self):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self)
        url, username, password = get_mergin_auth()
        self.ui.merginURL.setText(url)
        self.ui.username.setText(username)
        self.ui.password.setText(password)
        self.ui.test_connection_btn.clicked.connect(self.test_connection)
        self.ui.test_status.setText('')

    def writeSettings(self):
        url = self.ui.merginURL.text()
        username = self.ui.username.text()
        password = self.ui.password.text()
        set_mergin_auth(url, username, password)
        # reset token
        settings = QSettings()
        settings.setValue('Mergin/auth_token', None)

    def test_connection(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        url = self.ui.merginURL.text()
        username = self.ui.username.text()
        password = self.ui.password.text()
        try:
            mc = MerginClient(url, None, username, password)
            msg = "<font color=green> OK </font>"
        except (URLError, ValueError):
            msg = "<font color=red> Connection failed, incorrect URL </font>"
        except ClientError:
            msg = "<font color=red> Connection failed, incorrect username/password </font>"
        QApplication.restoreOverrideCursor()
        self.ui.test_status.setText(msg)
