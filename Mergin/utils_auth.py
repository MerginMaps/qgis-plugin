import datetime
import typing
import uuid
import json
from urllib.error import URLError
import requests
import urllib3

from qgis.core import (
    QgsApplication,
    QgsAuthMethodConfig,
    QgsBlockingNetworkRequest,
    QgsNetworkAccessManager,
    QgsExpressionContextUtils,
)
from qgis.PyQt.QtCore import QSettings, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from .mergin.client import LoginType, MerginClient, AuthTokenExpiredError, ServerType
from .mergin.common import ClientError, LoginError

from .utils import MERGIN_URL, get_qgis_proxy_config, get_plugin_version


class SSOLoginError(Exception):
    pass


class MissingAuthConfigError(Exception):
    pass


def get_login_type() -> LoginType:
    settings = QSettings()
    # default is password login
    login_type = LoginType(settings.value("Mergin/login_type", LoginType.PASSWORD))
    return login_type


def get_stored_mergin_server_url() -> str:
    settings = QSettings()
    mergin_url = settings.value("Mergin/server", MERGIN_URL)
    return mergin_url


def get_authcfg() -> typing.Optional[str]:
    settings = QSettings()
    authcfg = settings.value("Mergin/authcfg", None)
    return authcfg


def get_mergin_auth_cfg() -> QgsAuthMethodConfig:
    authcfg = get_authcfg()

    cfg = QgsAuthMethodConfig()
    auth_manager = QgsApplication.authManager()
    auth_manager.setMasterPassword()
    auth_manager.loadAuthenticationConfig(authcfg, cfg, True)

    return cfg


def set_mergin_auth_password(url: str, username: str, password: str, auth_token: typing.Optional[str] = None) -> None:
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
    cfg = get_mergin_auth_cfg()

    cfg.setUri(url)
    cfg.setConfig("username", None)
    cfg.setConfig("password", None)
    cfg.setConfig("mergin_access_token", auth_token)
    cfg.setConfig("email", sso_email)

    store_mergin_authcfg_id(cfg)


def store_mergin_authcfg_id(cfg: QgsAuthMethodConfig) -> None:
    if not cfg.id():
        cfg.setMethod("Basic")
        cfg.setName("mergin")
        _, cfg = QgsApplication.authManager().storeAuthenticationConfig(cfg)
    else:
        QgsApplication.authManager().updateAuthenticationConfig(cfg)

    settings = QSettings()
    settings.setValue("Mergin/authcfg", cfg.id())


def set_mergin_settings(url: str, login_type: LoginType) -> None:
    settings = QSettings()
    settings.setValue("Mergin/server", url)
    settings.setValue("Mergin/login_type", str(login_type))


def validate_mergin_session_not_expired(mc: MerginClient) -> bool:
    """Check if there are at least 5 seconds left before the Mergin Maps session expires."""
    if not mc._auth_session:
        return False
    delta = mc._auth_session["expire"] - datetime.datetime.now(datetime.timezone.utc)
    if delta.total_seconds() > 5:
        return True
    return False


def get_mergin_username_password() -> typing.Tuple[str, str]:
    cfg = get_mergin_auth_cfg()

    if cfg.id():
        username = cfg.config("username", None)
        password = cfg.config("password", None)
        if username and password:
            return username, password

    return "", ""


def get_mergin_sso_email() -> str:
    settings = QSettings()
    email = settings.value("Mergin/sso_email", None)
    return email


def get_mergin_auth_token(cfg: QgsAuthMethodConfig) -> str:
    auth_token = cfg.config("mergin_access_token", None)
    return auth_token


def create_mergin_client() -> MerginClient:
    login_type = get_login_type()
    url = get_stored_mergin_server_url()

    cfg = get_mergin_auth_cfg()

    if not cfg.id():
        raise MissingAuthConfigError

    if cfg.id():
        auth_token = get_mergin_auth_token(cfg)
        if auth_token:
            mc = MerginClient(
                url, auth_token, None, None, get_plugin_version(), get_qgis_proxy_config(url), login_type=login_type
            )
            if validate_mergin_session_not_expired(mc):
                return mc
            else:
                raise AuthTokenExpiredError("Auth token expired.")

        else:
            if login_type == LoginType.PASSWORD:
                username = cfg.config("username", None)
                password = cfg.config("password", None)
                if username and password:
                    mc = MerginClient(url, None, username, password, get_plugin_version(), get_qgis_proxy_config(url))
                    if validate_mergin_session_not_expired(mc):
                        return mc
                    else:
                        raise AuthTokenExpiredError("Auth token expired after re-log.")
                else:
                    raise ClientError("Username and password not found in config.")

            elif login_type == LoginType.SSO:
                raise ClientError("Auth token not found in config.")
    else:
        raise ValueError("Auth config not found.")


def validate_sso_login(server_url: str) -> bool:
    """Validate that there is existing sso login that is not expired."""
    try:
        cfg = get_mergin_auth_cfg()

        # validating against different server than is stored
        if cfg.uri() != server_url:
            return False

        token = get_mergin_auth_token(cfg)
        mc = MerginClient(
            server_url,
            auth_token=token,
            plugin_version=get_plugin_version(),
            proxy_config=get_qgis_proxy_config(server_url),
        )
        return validate_mergin_session_not_expired(mc)

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
        "queryPairs": {"state": str(uuid.uuid4())},
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
        if not validate_sso_login(url):
            try:
                oauth2_client_id = sso_oauth_client_id(url, sso_email)
                login_sso(url, oauth2_client_id)
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
        return False, "Server URL is not reachable"

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
    except (requests.RequestException, urllib3.exceptions.LocationParseError):
        return False
    return True
