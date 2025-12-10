# GPLv3 license
# Copyright Lutra Consulting Limited

import hashlib
import os
import re
import typing
import uuid
import json
from urllib.error import URLError
import requests
import urllib3
from enum import Enum

from qgis.core import (
    QgsApplication,
    QgsAuthMethodConfig,
    QgsBlockingNetworkRequest,
    QgsNetworkAccessManager,
    QgsExpressionContextUtils,
    Qgis,
    QgsProject,
    QgsProviderRegistry,
)
from qgis.PyQt.QtCore import QSettings, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.PyQt.QtWidgets import QMessageBox

from .mergin.client import MerginClient, ServerType, AuthTokenExpiredError
from .mergin.common import ClientError, LoginError, ProjectRole
from .mergin.merginproject import MerginProject

from .utils import MERGIN_URL, get_qgis_proxy_config, get_plugin_version


AUTH_CONFIG_FILENAME = "qgis_cfg.xml"


class LoginType(Enum):
    """Types of login supported by Mergin Maps."""

    PASSWORD = "password"  # classic login with username and password
    SSO = "sso"  # login with SSO token

    def __str__(self) -> str:
        return self.value


class SSOLoginError(Exception):
    pass


class MissingAuthConfigError(Exception):
    pass


def get_login_type() -> LoginType:
    """Get login type from Settings."""
    settings = QSettings()
    # default is password login
    login_type = LoginType(settings.value("Mergin/login_type", LoginType.PASSWORD))
    return login_type


def get_stored_mergin_server_url() -> str:
    """Get stored Mergin server URL from Settings."""
    settings = QSettings()
    mergin_url = settings.value("Mergin/server", MERGIN_URL)
    return mergin_url


def get_authcfg() -> typing.Optional[str]:
    """Get Mergin auth config ID from Settings."""
    settings = QSettings()
    authcfg = settings.value("Mergin/authcfg", None)
    return authcfg


def get_mergin_auth_cfg() -> QgsAuthMethodConfig:
    """Get Mergin auth config from QGIS auth manager."""
    authcfg = get_authcfg()

    cfg = QgsAuthMethodConfig()
    auth_manager = QgsApplication.authManager()
    auth_manager.setMasterPassword()
    auth_manager.loadAuthenticationConfig(authcfg, cfg, True)

    return cfg


def set_mergin_auth_password(url: str, username: str, password: str, auth_token: typing.Optional[str] = None) -> None:
    """
    Set Mergin auth config with username, password and optional auth token.
    Stored in QGIS auth manager.
    """

    cfg = get_mergin_auth_cfg()

    cfg.setUri(url)
    cfg.setConfig("username", username)
    cfg.setConfig("password", password)

    if not auth_token:
        mc = MerginClient(
            url,
            auth_token=None,
            login=username,
            password=password,
            plugin_version=get_plugin_version(),
            proxy_config=get_qgis_proxy_config(),
        )
        auth_token = mc._auth_session["token"]

    cfg.setConfig("mergin_access_token", auth_token)

    store_mergin_authcfg_id(cfg)


def set_mergin_auth_sso(url: str, auth_token: str, sso_email: typing.Optional[str]) -> None:
    """
    Set Mergin auth config for SSO login with auth token and optional email.
    Stored in QGIS auth manager.
    """

    cfg = get_mergin_auth_cfg()

    cfg.setUri(url)
    cfg.setConfig("username", None)
    cfg.setConfig("password", None)
    cfg.setConfig("mergin_access_token", auth_token)
    cfg.setConfig("email", sso_email)

    store_mergin_authcfg_id(cfg)


def store_mergin_authcfg_id(cfg: QgsAuthMethodConfig) -> None:
    """Store Mergin auth config ID in QGIS auth manager and settings."""
    if not cfg.id():
        cfg.setMethod("Basic")
        cfg.setName("mergin")
        _, cfg = QgsApplication.authManager().storeAuthenticationConfig(cfg)
    else:
        QgsApplication.authManager().updateAuthenticationConfig(cfg)

    settings = QSettings()
    settings.setValue("Mergin/authcfg", cfg.id())


def set_mergin_settings(url: str, login_type: LoginType) -> None:
    """Set Mergin server URL and login type in Settings."""
    settings = QSettings()
    settings.setValue("Mergin/server", url)
    settings.setValue("Mergin/login_type", str(login_type))


def get_mergin_username_password() -> typing.Tuple[str, str]:
    """Get Mergin username and password from auth config."""
    cfg = get_mergin_auth_cfg()

    if cfg.id():
        username = cfg.config("username", None)
        password = cfg.config("password", None)
        if username and password:
            return username, password

    return "", ""


def get_mergin_sso_email() -> str:
    """Get Mergin SSO email from Settings."""
    settings = QSettings()
    email = settings.value("Mergin/sso_email", None)
    return email


def get_mergin_auth_token(cfg: QgsAuthMethodConfig) -> str:
    """Get Mergin auth token from auth config."""
    auth_token = cfg.config("mergin_access_token", None)
    return auth_token


def create_mergin_client() -> MerginClient:
    """
    Create a MerginClient instance based on stored auth config.
    Raises exceptions if auth config is missing or invalid.
    """

    login_type = get_login_type()
    url = get_stored_mergin_server_url()

    cfg = get_mergin_auth_cfg()

    if not cfg.id():
        raise MissingAuthConfigError

    if cfg.id():
        auth_token = get_mergin_auth_token(cfg)
        if auth_token:
            if login_type == LoginType.SSO:
                mc = MerginClient(
                    url,
                    auth_token,
                    None,
                    None,
                    get_plugin_version(),
                    get_qgis_proxy_config(url),
                )
                return mc
            else:
                username, password = get_mergin_username_password()
                mc = MerginClient(
                    url,
                    auth_token,
                    username,
                    password,
                    get_plugin_version(),
                    get_qgis_proxy_config(url),
                )
                mc.validate_auth()
                return mc
        else:
            if login_type == LoginType.PASSWORD:
                username = cfg.config("username", None)
                password = cfg.config("password", None)
                if username and password:
                    mc = MerginClient(
                        url,
                        None,
                        username,
                        password,
                        get_plugin_version(),
                        get_qgis_proxy_config(url),
                    )
                    mc.validate_auth()
                    return mc
                else:
                    raise ClientError("Username and password not found in config.")

            elif login_type == LoginType.SSO:
                raise ClientError("Auth token not found in config.")
    else:
        raise ValueError("Auth config not found.")


def validate_sso_login(server_url: str, sso_email: typing.Optional[str] = None) -> bool:
    """Validate that there is existing sso login that is not expired."""
    try:
        cfg = get_mergin_auth_cfg()

        # validating against different server than is stored
        if cfg.uri() != server_url:
            return False

        if cfg.config("password", None) or cfg.config("username", None):
            return False

        if cfg.config("email", None) != sso_email:
            return False

        token = get_mergin_auth_token(cfg)
        mc = MerginClient(
            server_url,
            auth_token=token,
            plugin_version=get_plugin_version(),
            proxy_config=get_qgis_proxy_config(server_url),
        )
        try:
            mc.validate_auth()
            return True
        except (AuthTokenExpiredError, ClientError):
            return False

    except MissingAuthConfigError:
        return False


def login_sso(server_url: str, oauth2_client_id: str, email: typing.Optional[str] = None) -> None:
    """
    Login to Mergin Maps using SSO.

    This ensures that AuthConfig with name "mmmmsso" is created and
    configs "mergin_access_token" and "mergin_access_token_expire_date" exist on it.
    """

    # add/update SSO config
    config_dict = {
        "accessMethod": 0,
        "apiKey": "",
        "clientId": oauth2_client_id,
        "clientSecret": "",
        "configType": 1,
        "customHeader": "",
        "description": "",
        "grantFlow": 3,
        "id": "mmmmsso",
        "name": "Mergin Maps SSO",
        "objectName": "",
        "password": "",
        "persistToken": False,
        "queryPairs": {
            "state": str(uuid.uuid4()),
            "login_hint": email,
        },
        "redirectHost": "localhost",  # if this changes we need to inform server team about it to update the SSO config
        "redirectPort": 10042,  # if this changes we need to inform server team about it to update the SSO config
        "redirectUrl": "qgis",
        "refreshTokenUrl": "",
        "requestTimeout": 30,
        "requestUrl": f"{server_url}/v2/sso/authorize",
        "scope": "",
        "tokenUrl": f"{server_url}/v2/sso/token",
        "username": "",
        "version": 1,
    }
    config_json = json.dumps(config_dict)
    config = QgsAuthMethodConfig(method="OAuth2")
    config.setName("Mergin Maps SSO")
    config.setId("mmmmsso")
    config.setConfig("oauth2config", config_json)
    if "mmmmsso" in QgsApplication.authManager().configIds():
        QgsApplication.authManager().updateAuthenticationConfig(config)
    else:
        QgsApplication.authManager().storeAuthenticationConfig(config)

    # create request and open login page if needed
    ok, request = QgsApplication.authManager().updateNetworkRequest(
        QNetworkRequest(QUrl(f"{server_url}/ping")), "mmmmsso"
    )
    if not ok:
        raise SSOLoginError("SSO login failed, cannot create network request.")
    reply = QgsNetworkAccessManager.instance().get(request)
    access_token = bytes(reply.request().rawHeader(b"Authorization"))  # includes "Bearer ...."

    # create mergin client using the token
    access_token_str = access_token.decode("utf-8")

    try:
        mc = MerginClient(
            server_url,
            auth_token=access_token_str,
            plugin_version=get_plugin_version(),
            proxy_config=get_qgis_proxy_config(server_url),
        )
    except (URLError, ClientError, LoginError) as e:
        QgsApplication.messageLog().logMessage(f"Mergin Maps plugin: {str(e)}")
        mc = None

    if mc:
        set_mergin_auth_sso(url=server_url, auth_token=mc._auth_session["token"], sso_email=email)


def json_response(url: str) -> dict:
    """
    Parse url response in JSON to dictionary.

    Raise errors if the response is not JSON or if the request fails.
    """
    br = QgsBlockingNetworkRequest()
    error = br.get(QNetworkRequest(QUrl(url)))

    if error == QgsBlockingNetworkRequest.ErrorCode.ServerExceptionError:
        raise ValueError("Server error")

    if error != QgsBlockingNetworkRequest.ErrorCode.NoError:
        raise URLError("Failed to get url")

    json_raw_data = bytes(br.reply().content())

    try:
        json_data = json.loads(json_raw_data)
    except json.JSONDecodeError as exc:
        raise ValueError("Failed to decode JSON response") from exc

    return json_data


def sso_oauth_client_id(server_url: str, email: typing.Optional[str] = None) -> str:
    """
    Get OAuth2 client ID for SSO login from server.

    Raise issue if the id data is not found.
    """
    if email:
        json_data = json_response(f"{server_url}/v2/sso/connections?email={email}")
        id_name = "id"
    else:
        json_data = json_response(f"{server_url}/v2/sso/config")
        id_name = "client_id"

    if id_name not in json_data:
        raise SSOLoginError("SSO login failed missing id in response.")

    oauth2_client_id = json_data[id_name]
    return oauth2_client_id


def test_server_connection(
    url,
    username: typing.Optional[str] = None,
    password: typing.Optional[str] = None,
    use_sso: bool = False,
    sso_email: typing.Optional[str] = None,
) -> typing.Tuple[bool, str]:
    """
    Test connection to Mergin Maps server. This includes check for valid server URL
    and user credentials correctness.
    """
    if not url_reachable(url):
        msg = "<font color=red> Server URL is not reachable </font>"
        QgsApplication.messageLog().logMessage(f"Mergin Maps plugin: {msg}")
        return False, msg

    err_msg = validate_mergin_url(url)
    if err_msg:
        msg = f"<font color=red>{err_msg}</font>"
        QgsApplication.messageLog().logMessage(f"Mergin Maps plugin: {err_msg}")
        return False, msg

    result = True, "<font color=green> OK </font>"
    proxy_config = get_qgis_proxy_config(url)

    if not use_sso:
        if username is None or password is None:
            msg = "<font color=red> Username and password are required </font>"
            QgsApplication.messageLog().logMessage(f"Mergin Maps plugin: {msg}")
            return False, msg
        try:
            MerginClient(url, None, username, password, get_plugin_version(), proxy_config)
        except (LoginError, ClientError, AuthTokenExpiredError) as e:
            QgsApplication.messageLog().logMessage(f"Mergin Maps plugin: {str(e)}")
            result = False, f"<font color=red> Connection failed, {str(e)} </font>"
    else:
        if not validate_sso_login(url, sso_email):
            try:
                oauth2_client_id = sso_oauth_client_id(url, sso_email)
                login_sso(url, oauth2_client_id, sso_email)
            except (URLError, ValueError, SSOLoginError) as e:
                result = False, f"<font color=red> Connection failed, {str(e)} </font>"
    return result


def validate_mergin_url(url):
    """
    Initiates connection to the provided server URL to check if the server is accessible
    :param url: String Mergin Maps URL to ping.
    :return: String error message as result of validation. If None, URL is valid.
    """
    try:
        MerginClient(url, proxy_config=get_qgis_proxy_config(url))

    # Valid but not Mergin URl
    except ClientError:
        return "Invalid Mergin Maps URL"
    # Cannot parse URL
    except ValueError:
        return "Invalid URL"
    return None


def sso_login_allowed(url: str) -> typing.Tuple[bool, typing.Optional[str]]:
    """Tests if SSO login is allowed on the server. Returns a tuple with a boolean and an optional error message."""
    if not url_reachable(url):
        return False, None

    try:
        server_config_data = json_response(f"{url}/config")
    except URLError as e:
        return False, f"Could not connect to server: {str(e)}"
    except ValueError as e:
        return False, f"Could not parse server response: {str(e)}"

    if "sso_enabled" in server_config_data:
        sso_enabled = server_config_data["sso_enabled"]
        if sso_enabled:
            return True, None

    return False, None


def sso_ask_for_email(url: str) -> typing.Tuple[bool, typing.Optional[str]]:
    """Tests if SSO login should ask for email. Returns a tuple with a boolean and an optional error message."""
    if not url_reachable(url):
        return True, None

    try:
        json_data = json_response(f"{url}/v2/sso/config")
    except URLError as e:
        return True, f"Could not connect to server: {str(e)}"
    except ValueError as e:
        return True, f"Could not parse server response: {str(e)}"

    if "tenant_flow_type" not in json_data:
        return True, "Server response did not contain required tenant_flow_type data"

    if json_data["tenant_flow_type"] not in ["multi", "single"]:
        return True, "SSO tenant_flow_type is not valid"

    if json_data["tenant_flow_type"] == "multi":
        return True, None

    return False, None


def set_qgsexpressionscontext(url: str, mc: typing.Optional[MerginClient] = None):
    QgsExpressionContextUtils.setGlobalVariable("mergin_url", url)
    QgsExpressionContextUtils.setGlobalVariable("mm_url", url)
    if mc:
        # username can be username or email, so we fetch it from api
        user_info = mc.user_info()
        username = user_info["username"]
        user_email = user_info["email"]
        user_full_name = user_info["name"]
        settings = QSettings()
        settings.setValue("Mergin/username", username)
        settings.setValue("Mergin/user_email", user_email)
        settings.setValue("Mergin/full_name", user_full_name)
        QgsExpressionContextUtils.setGlobalVariable("mergin_username", username)
        QgsExpressionContextUtils.setGlobalVariable("mergin_user_email", user_email)
        QgsExpressionContextUtils.setGlobalVariable("mergin_full_name", user_full_name)
        QgsExpressionContextUtils.setGlobalVariable("mm_username", username)
        QgsExpressionContextUtils.setGlobalVariable("mm_user_email", user_email)
        QgsExpressionContextUtils.setGlobalVariable("mm_full_name", user_full_name)
    else:
        QgsExpressionContextUtils.removeGlobalVariable("mergin_username")
        QgsExpressionContextUtils.removeGlobalVariable("mergin_user_email")
        QgsExpressionContextUtils.removeGlobalVariable("mergin_full_name")
        QgsExpressionContextUtils.removeGlobalVariable("mm_username")
        QgsExpressionContextUtils.removeGlobalVariable("mm_user_email")
        QgsExpressionContextUtils.removeGlobalVariable("mm_full_name")


def mergin_server_deprecated_version(url: str) -> bool:
    mc = MerginClient(
        url=url,
        auth_token=None,
        login=None,
        password=None,
        plugin_version=get_plugin_version(),
        proxy_config=get_qgis_proxy_config(url),
    )

    if mc.server_type() == ServerType.OLD:
        return True

    return False


def url_reachable(url: str) -> bool:
    try:
        requests.get(url, timeout=3)
    except (
        requests.RequestException,
        urllib3.exceptions.LocationParseError,
        UnicodeError,
    ):
        return False
    return True


def qgis_support_sso() -> bool:
    """
    Check if the current QGIS version supports SSO login.
    Returns True if SSO is supported, False otherwise.
    """
    # QGIS 3.40+ supports SSO
    return Qgis.versionInt() >= 34000


class AuthSync:
    def __init__(self, qgis_file=None):
        if qgis_file is None:
            self.project = QgsProject.instance()
        else:
            self.project = QgsProject()
            self.project.read(qgis_file)
        self.project_path = self.project.homePath()
        self.auth_file = os.path.join(self.project_path, AUTH_CONFIG_FILENAME)
        self.mp = MerginProject(self.project_path)
        self.project_id = self.mp.project_id()
        self.auth_mngr = QgsApplication.authManager()

    def get_layers_auth_ids(self) -> list[str]:
        """Get the auth config IDs of the protected layers in the current project."""
        auth_ids = set()
        reg = QgsProviderRegistry.instance()
        for layer in self.project.mapLayers().values():
            source = layer.source()
            prov_type = layer.providerType()
            decoded_uri = reg.decodeUri(prov_type, source)
            auth_id = decoded_uri.get("authcfg")
            if auth_id:
                auth_ids.add(auth_id)
        return list(auth_ids)

    def get_auth_config_hash(self, auth_ids: list[str]) -> str:
        """
        Generates a stable hash from the decrypted content of the given auth IDs.
        This allows us to detect config changes regardless of random encryption salts in the encrypted XML file.
        """
        sorted_ids = sorted(auth_ids)

        hasher = hashlib.sha256()

        for auth_id in sorted_ids:
            config = QgsAuthMethodConfig()
            if not self.auth_mngr.loadAuthenticationConfig(auth_id, config, True):  # True to decrypt full details
                self.mp.log.error(f"Failed to load the authentication config for the auth ID: {auth_id}")
                continue

            header_data = f"{config.id()}|{config.method()}|{config.uri()}"
            hasher.update(header_data.encode("utf-8"))

            config_map = config.configMap()
            for key in sorted(config_map.keys()):
                entry = f"|{key}={config_map[key]}"
                hasher.update(entry.encode("utf-8"))

        return hasher.hexdigest()

    def export_auth(self, client) -> None:
        """Export auth DB credentials for protected layers if they have changed"""

        auth_ids = self.get_layers_auth_ids()
        if not auth_ids:
            if os.path.exists(self.auth_file):
                os.remove(self.auth_file)
            return
        project_info = client.project_info(self.mp.project_full_name())
        role = project_info.get("role")
        if not (role and role in ("writer", "owner")):
            return

        if not self.auth_mngr.masterPasswordIsSet():
            self.mp.log.warning("Master Password not set. Cannot export auth configs.")
            msg = "Failed to export authentication configuration. If you want to share the credentials of the protected layer(s), set the master password please."
            QMessageBox.warning(
                None, "Cannot export configuration for protected layer", msg, QMessageBox.StandardButton.Close
            )
            return

        current_hash = self.get_auth_config_hash(auth_ids)

        # Compare current hash with the hash in the existing file
        file_exists = os.path.exists(self.auth_file)
        if file_exists:
            with open(self.auth_file, "r", encoding="utf-8") as f:
                content = f.read()
                pattern = r"<!--\s*HASH:\s*([A-Za-z0-9]+)\s*-->"
                match = re.search(pattern, content)
                if match:
                    existing_hash = match.group(1)
                    if existing_hash == current_hash:
                        self.mp.log.info("No change in auth config. No update needed.")
                        return
                    else:
                        self.mp.log.info("Auth config file change detected. Updating file...")
                else:
                    self.mp.log.warning("No hash found in existing config file. Creating one...")

        # Export and inject hash
        temp_file = os.path.join(self.project_path, f"temp_{AUTH_CONFIG_FILENAME}")

        ok = self.auth_mngr.exportAuthenticationConfigsToXml(temp_file, list(auth_ids), self.project_id)

        if ok:
            with open(temp_file, "r", encoding="utf-8") as f:
                xml_content = f.read()

            hashed_content = xml_content + f"\n<!-- HASH: {current_hash} -->"

            with open(self.auth_file, "w", encoding="utf-8") as f:
                f.write(hashed_content)

            if os.path.exists(temp_file):
                os.remove(temp_file)

    def import_auth(self) -> None:
        """Import credentials for protected layers"""

        if os.path.isfile(self.auth_file):
            if not self.auth_mngr.masterPasswordIsSet():
                self.mp.log.warning("Master password is not set. Could not import auth config.")
                user_msg = "Could not import authentication configuration for the protected layer(s). Set the master password and reload the project if you want to access the protected layer(s)."
                QMessageBox.warning(None, "Could not load protected layer", user_msg, QMessageBox.StandardButton.Close)
                return

            ok = self.auth_mngr.importAuthenticationConfigsFromXml(self.auth_file, self.project_id, overwrite=True)
            self.mp.log.info(f"QGIS auth imported: {ok}")
