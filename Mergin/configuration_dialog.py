# GPLv3 license
# Copyright Lutra Consulting Limited

import os
import typing
from qgis.PyQt.QtWidgets import QDialog, QApplication, QDialogButtonBox, QMessageBox
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QSettings, QTimer
from qgis.PyQt.QtGui import QPixmap
from qgis.core import QgsApplication, Qgis
from urllib.error import URLError


from .utils_auth import (
    LoginType,
    get_login_type,
    get_mergin_sso_email,
    get_stored_mergin_server_url,
    get_mergin_username_password,
    set_mergin_settings,
    test_server_connection,
    set_mergin_auth_password,
    validate_sso_login,
    sso_login_allowed,
    sso_ask_for_email,
    mergin_server_deprecated_version,
    url_reachable,
    qgis_support_sso,
)
from .utils import (
    MERGIN_URL,
    mm_logo_path,
    is_dark_theme,
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

        url = get_stored_mergin_server_url()

        if login_type == LoginType.PASSWORD:
            username, password = get_mergin_username_password()
            self.ui.username.setText(username)
            self.ui.password.setText(password)
            self.ui.stacked_widget_login.setCurrentIndex(0)
        elif login_type == LoginType.SSO:
            self.ui.sso_email.setText(get_mergin_sso_email())
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
        self.ui.merginURL.textChanged.connect(self.check_sso_email)
        self.ui.sso_email.textChanged.connect(self.check_credentials)
        self.ui.stacked_widget_login.currentChanged.connect(self.check_credentials)

        self.sso_email_required = False

        self.ui.button_sign_sso.clicked.connect(self.show_sign_sso)
        self.ui.button_sign_password.clicked.connect(self.show_sign_email)

        self.check_credentials()
        self.check_sso_availability()

        if not qgis_support_sso():
            self.ui.button_sign_sso.setVisible(False)
            self.ui.stacked_widget_login.setCurrentIndex(0)
            self.ui.sso_email.setVisible(False)

    def accept(self):
        if not self.test_connection():
            return

        url = self.server_url()
        set_mergin_settings(url=url, login_type=self.login_type())

        if self.login_type() == LoginType.PASSWORD:
            set_mergin_auth_password(url=url, username=self.ui.username.text(), password=self.ui.password.text())
        else:
            settings = QSettings()
            settings.setValue("Mergin/sso_email", self.ui.sso_email.text())

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
            if self.sso_email_required:
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

    def test_connection(self):

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        if self.login_type() == LoginType.PASSWORD:
            ok, msg = test_server_connection(self.server_url(), self.ui.username.text(), self.ui.password.text())
        else:
            if validate_sso_login(self.server_url(), self.get_sso_email()):
                self.ui.test_status.setText("<font color=green> OK </font>")
                QApplication.restoreOverrideCursor()
                return True

            self.ui.test_status.setText(f"<font color=orange>Follow the instructions in the browser...</font>")
            ok, msg = test_server_connection(self.server_url(), use_sso=True, sso_email=self.get_sso_email())

        if url_reachable(self.server_url()):
            if mergin_server_deprecated_version(self.server_url()):
                msg = "This server is running an outdated version that will no longer be supported. Please contact your server administrator to upgrade."
                QMessageBox.information(
                    self,
                    "Deprecated server version",
                    msg,
                )
                self.ui.test_status.setText(f"<font color=red> {msg} </font>")
                QApplication.restoreOverrideCursor()
                return False
        else:
            msg = "<font color=red> Server URL is not reachable </font>"
            self.ui.test_status.setText(msg)
            QApplication.restoreOverrideCursor()
            return False

        self.ui.test_status.setText(msg)
        QApplication.restoreOverrideCursor()
        return ok

    def allow_sso_login(self) -> None:
        self.ui.button_sign_sso.setVisible(False)

        if not qgis_support_sso():
            return

        allowed, msg = sso_login_allowed(self.server_url())
        if msg:
            QMessageBox.critical(self, "SSO allowed check", msg)
            return

        if allowed:
            self.sso_email_required, msg = sso_ask_for_email(self.server_url())
            if msg:
                QMessageBox.critical(self, "SSO email check", msg)

        self.ui.button_sign_sso.setVisible(allowed)
        self.ui.sso_email.setVisible(self.sso_email_required)

        if not allowed:
            self.ui.stacked_widget_login.setCurrentIndex(0)

    def check_sso_availability(self) -> None:
        self.sso_timer = QTimer(self)
        self.sso_timer.setSingleShot(True)
        self.sso_timer.start(1000)
        self.sso_timer.timeout.connect(self.allow_sso_login)

    def check_sso_email(self) -> None:
        self.sso_email_timer = QTimer(self)
        self.sso_email_timer.setSingleShot(True)
        self.sso_email_timer.start(1000)
        self.sso_email_timer.timeout.connect(self.enable_sso_email_input)

    def show_sign_sso(self) -> None:
        self.ui.stacked_widget_login.setCurrentIndex(1)
        self.enable_sso_email_input()

    def enable_sso_email_input(self) -> None:
        self.ui.sso_email.setVisible(self.sso_email_required)

    def show_sign_email(self) -> None:
        self.ui.stacked_widget_login.setCurrentIndex(0)

    def get_sso_email(self) -> typing.Optional[str]:
        if self.sso_email_required:
            if self.ui.sso_email.isVisible():
                return self.ui.sso_email.text()
        return None
