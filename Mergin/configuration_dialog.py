# GPLv3 license
# Copyright Lutra Consulting Limited

import os
import typing
from qgis.PyQt.QtWidgets import QDialog, QApplication, QDialogButtonBox, QMessageBox
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QSettings, QTimer
from qgis.PyQt.QtGui import QPixmap
from qgis.core import QgsApplication, QgsExpressionContextUtils
from urllib.error import URLError

try:
    from .mergin.client import MerginClient, ClientError, LoginError
except ImportError:
    import sys

    this_dir = os.path.dirname(os.path.realpath(__file__))
    path = os.path.join(this_dir, "mergin_client.whl")
    sys.path.append(path)
    from mergin.client import MerginClient, ClientError, LoginError

from .utils import (
    get_mergin_auth,
    set_mergin_auth,
    MERGIN_URL,
    create_mergin_client,
    get_plugin_version,
    get_qgis_proxy_config,
    test_server_connection,
    mm_logo_path,
    is_dark_theme,
    LoginType,
    get_login_type,
    login_sso,
    validate_sso_login,
    json_response,
    sso_oauth_client_id,
    SSOLoginError,
)

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_config.ui")


class ConfigurationDialog(QDialog):
    def __init__(self):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self)
        settings = QSettings()
        if is_dark_theme():
            self.ui.label.setText(
                "Don't have an account yet? <a style='color:#88b2f5' href='https://app.merginmaps.com/register'>Sign up</a> now!"
            )
        else:
            self.ui.label.setText(
                "Don't have an account yet? <a href='https://app.merginmaps.com/register'>Sign up</a> now!"
            )

        save_credentials = settings.value("Mergin/saveCredentials", "false").lower() == "true"
        login_type = get_login_type()
        if save_credentials or login_type == LoginType.PASSWORD:
            QgsApplication.authManager().setMasterPassword()

        if login_type == LoginType.PASSWORD:
            url, username, password = get_mergin_auth()
            self.ui.username.setText(username)
            self.ui.password.setText(password)
        elif login_type == LoginType.SSO:
            url, sso_email, _ = get_mergin_auth()
            self.ui.sso_email.setText(sso_email)
            self.ui.stacked_widget_login.setCurrentIndex(1)

        self.ui.label_logo.setPixmap(QPixmap(mm_logo_path()))
        self.ui.merginURL.setText(url)
        self.ui.save_credentials.setChecked(save_credentials)
        self.ui.test_connection_btn.clicked.connect(self.test_connection)
        self.ui.test_status.setText("")
        self.ui.master_password_status.setText("")
        self.ui.custom_url.setChecked(url.rstrip("/") != MERGIN_URL)
        self.ui.merginURL.setVisible(self.ui.custom_url.isChecked())
        self.ui.custom_url.stateChanged.connect(self.toggle_custom_url)
        self.ui.save_credentials.stateChanged.connect(self.check_master_password)
        self.ui.username.textChanged.connect(self.check_credentials)
        self.ui.password.textChanged.connect(self.check_credentials)
        self.ui.merginURL.textChanged.connect(self.check_sso_availability)

        self.ui.button_sign_sso.clicked.connect(self.show_sign_sso)
        self.ui.button_sign_password.clicked.connect(self.show_sign_email)

        self.check_credentials()
        self.allow_sso_login()

        # self.ui.sso_btn.clicked.connect(self.sso)

    def accept(self):
        if not self.test_connection():
            return

        super().accept()

    def toggle_custom_url(self):
        self.ui.merginURL.setVisible(self.ui.custom_url.isChecked())

    def server_url(self):
        return self.ui.merginURL.text() if self.ui.custom_url.isChecked() else MERGIN_URL

    def check_credentials(self):
        enable_buttons = False
        if self.login_type() == LoginType.PASSWORD:
            enable_buttons = bool(self.ui.username.text()) and bool(self.ui.password.text())
        elif self.login_type() == LoginType.SSO:
            if self.sso_ask_for_email():
                enable_buttons = bool(self.ui.sso_email.text())
            else:
                enable_buttons = True
        self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setEnabled(enable_buttons)
        self.ui.test_connection_btn.setEnabled(enable_buttons)

    def check_master_password(self):
        if not self.ui.save_credentials.isChecked():
            self.ui.master_password_status.setText("")
            return

        if QgsApplication.authManager().masterPasswordIsSet():
            self.ui.master_password_status.setText("")
        else:
            self.ui.master_password_status.setText(
                "<font color=red> Warning: You may be prompted for QGIS master password </font>"
            )

    def login_type(self) -> LoginType:
        if self.ui.stacked_widget_login.currentIndex() == 0:
            return LoginType.PASSWORD
        elif self.ui.stacked_widget_login.currentIndex() == 1:
            return LoginType.SSO
        return LoginType.PASSWORD

    def writeSettings(self):
        url = self.server_url()
        username = self.ui.username.text()
        password = self.ui.password.text()
        settings = QSettings()
        settings.setValue("Mergin/auth_token", None)  # reset token
        settings.setValue("Mergin/saveCredentials", str(self.ui.save_credentials.isChecked()))
        settings.setValue("Mergin/username", username)
        settings.setValue("Mergin/sso_email", self.ui.sso_email.text())
        settings.setValue("Mergin/login_type", str(self.login_type()))

        if self.ui.save_credentials.isChecked():
            set_mergin_auth(url, username, password)
            try:
                mc = create_mergin_client()
            except (URLError, ClientError, LoginError):
                mc = None
        else:
            try:
                proxy_config = get_qgis_proxy_config(url)
                mc = MerginClient(url, None, username, password, get_plugin_version(), proxy_config)
                settings.setValue("Mergin/auth_token", mc._auth_session["token"])
                settings.setValue("Mergin/server", url)
            except (URLError, ClientError, LoginError) as e:
                QgsApplication.messageLog().logMessage(f"Mergin Maps plugin: {str(e)}")
                mc = None

        QgsExpressionContextUtils.setGlobalVariable("mergin_url", url)
        if mc:
            QgsExpressionContextUtils.setGlobalVariable("mergin_username", username)
        else:
            QgsExpressionContextUtils.removeGlobalVariable("mergin_username")

        return mc

    def test_connection(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        if self.login_type() == LoginType.PASSWORD:
            ok, msg = test_server_connection(self.server_url(), self.ui.username.text(), self.ui.password.text())
        else:
            ok, msg = test_server_connection(self.server_url(), use_sso=True, sso_email=self.get_sso_email())
        QApplication.restoreOverrideCursor()
        self.ui.test_status.setText(msg)
        return ok

    def allow_sso_login(self) -> None:
        self.ui.button_sign_sso.setVisible(False)

        try:
            server_config_data = json_response(f"{self.server_url()}/config")
        except (URLError, ValueError) as e:
            QMessageBox.critical(self, "SSO allowed check", str(e))
            return

        if "sso_enabled" in server_config_data:
            sso_enabled = server_config_data["sso_enabled"]
            if sso_enabled:
                self.ui.button_sign_sso.setVisible(True)

    def check_sso_availability(self) -> None:
        self.sso_timer = QTimer(self)
        self.sso_timer.setSingleShot(True)
        self.sso_timer.start(1000)
        self.sso_timer.timeout.connect(self.allow_sso_login)

    def show_sign_sso(self) -> None:
        self.ui.stacked_widget_login.setCurrentIndex(1)

        self.ui.sso_email.setVisible(self.sso_ask_for_email())

    def show_sign_email(self) -> None:
        self.ui.stacked_widget_login.setCurrentIndex(0)

    def get_sso_email(self) -> typing.Optional[str]:
        if self.ui.sso_email.isVisible():
            return self.ui.sso_email.text()
        return None

    def sso_ask_for_email(self) -> bool:

        try:
            json_data = json_response(f"{self.server_url()}/v2/sso/config")
        except (URLError, ValueError) as e:
            QMessageBox.critical(self, "SSO configuration check", str(e))

        if "tenant_flow_type" not in json_data:
            QMessageBox.critical(
                self, "Server Response Error", "Server response did not contain required tenant_flow_type data"
            )
            return True

        if json_data["tenant_flow_type"] not in ["multi", "single"]:
            QMessageBox.critical(self, "Server Response Error", "SSO tenant_flow_type is not valid")
            return True

        if json_data["tenant_flow_type"] == "multi":
            return True

        return False

    def login_using_sso(self) -> None:

        if validate_sso_login():
            return

        email = None
        if self.ui.sso_email.isVisible():
            email = self.ui.sso_email.text()

        try:
            oauth2_client_id = sso_oauth_client_id(self.server_url(), email)
        except (URLError, ValueError, SSOLoginError) as e:
            QMessageBox.critical(self, "SSO login check", str(e))
            return

        login_sso(self.server_url(), oauth2_client_id)
