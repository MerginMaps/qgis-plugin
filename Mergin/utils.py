import os
from datetime import datetime, timezone
from functools import wraps
import urllib.parse
import urllib.request
from urllib.error import URLError, HTTPError
from qgis.core import (
    QgsApplication,
    QgsAuthMethodConfig,
    QgsExpressionContextUtils,
    QgsProject,
)
from qgis.PyQt.QtCore import QSettings
from qgis.core import Qgis
import configparser
import platform


try:
    from .mergin import InvalidProject
    from .mergin.client import MerginClient, ClientError, LoginError
    from .mergin.client_pull import download_project_async, download_project_is_running, \
                                    download_project_finalize, download_project_cancel
    from .mergin.client_pull import pull_project_async, pull_project_is_running, \
                                    pull_project_finalize, pull_project_cancel
    from .mergin.client_push import push_project_async, push_project_is_running, \
                                    push_project_finalize, push_project_cancel
except ImportError:
    import sys
    this_dir = os.path.dirname(os.path.realpath(__file__))
    path = os.path.join(this_dir, 'mergin_client.whl')
    sys.path.append(path)
    from mergin.client import MerginClient, ClientError, InvalidProject, LoginError
    from mergin.client_pull import download_project_async, download_project_is_running, \
                                   download_project_finalize, download_project_cancel
    from mergin.client_pull import pull_project_async, pull_project_is_running, \
                                   pull_project_finalize, pull_project_cancel
    from mergin.client_push import push_project_async, push_project_is_running, \
                                   push_project_finalize, push_project_cancel

MERGIN_URL = 'https://public.cloudmergin.com'
MERGIN_LOGS_URL = 'https://g4pfq226j0.execute-api.eu-west-1.amazonaws.com/mergin_client_log_submit'


def find_qgis_files(directory):
    qgis_files = []
    for root, dirs, files in os.walk(directory):
        for f in files:
            _, ext = os.path.splitext(f)
            if ext in ['.qgs', '.qgz']:
                qgis_files.append(os.path.join(root, f))           
    return qgis_files


def get_mergin_auth():
    settings = QSettings()
    save_credentials = settings.value('Mergin/saveCredentials', 'false').lower() == 'true'
    mergin_url = settings.value('Mergin/server', MERGIN_URL)
    auth_manager = QgsApplication.authManager()
    if not save_credentials or not auth_manager.masterPasswordHashInDatabase():
        return mergin_url, '', ''

    authcfg = settings.value('Mergin/authcfg', None)
    cfg = QgsAuthMethodConfig()
    auth_manager.loadAuthenticationConfig(authcfg, cfg, True)
    url = cfg.uri()
    username = cfg.config('username')
    password = cfg.config('password')
    return url, username, password


def set_mergin_auth(url, username, password):
    settings = QSettings()
    authcfg = settings.value('Mergin/authcfg', None)
    cfg = QgsAuthMethodConfig()
    auth_manager = QgsApplication.authManager()
    auth_manager.setMasterPassword()
    auth_manager.loadAuthenticationConfig(authcfg, cfg, True)

    if cfg.id():
        cfg.setUri(url)
        cfg.setConfig("username", username)
        cfg.setConfig("password", password)
        auth_manager.updateAuthenticationConfig(cfg)
    else:
        cfg.setMethod("Basic")
        cfg.setName("mergin")
        cfg.setUri(url)
        cfg.setConfig("username", username)
        cfg.setConfig("password", password)
        auth_manager.storeAuthenticationConfig(cfg)
        settings.setValue('Mergin/authcfg', cfg.id())

    settings.setValue('Mergin/server', url)


def create_mergin_client():
    url, username, password = get_mergin_auth()
    settings = QSettings()
    auth_token = settings.value('Mergin/auth_token', None)
    if auth_token:
        mc = MerginClient(url, auth_token, username, password, get_plugin_version())
        # check token expiration
        delta = mc._auth_session['expire'] - datetime.now(timezone.utc)
        if delta.total_seconds() > 1:
            return mc

    if not (username and password):
        raise ClientError()

    try:
        mc = MerginClient(url, None, username, password, get_plugin_version())
    except (URLError, ClientError) as e:
        QgsApplication.messageLog().logMessage(str(e))
        raise
    settings.setValue('Mergin/auth_token', mc._auth_session['token'])
    return MerginClient(url, mc._auth_session['token'], username, password, get_plugin_version())


def get_qgis_version_str():
    """ Returns QGIS verion as 'MAJOR.MINOR.PATCH', for example '3.10.6' """
    # there's also Qgis.QGIS_VERSION which is string but also includes release name (possibly with unicode characters)
    qgis_ver_int = Qgis.QGIS_VERSION_INT
    qgis_ver_major = qgis_ver_int // 10000
    qgis_ver_minor = (qgis_ver_int % 10000) // 100
    qgis_ver_patch = (qgis_ver_int % 100)
    return "{}.{}.{}".format(qgis_ver_major, qgis_ver_minor, qgis_ver_patch)


def plugin_version():
    with open(os.path.join(os.path.dirname(__file__), "metadata.txt"), 'r') as f:
        config = configparser.ConfigParser()
        config.read_file(f)
    return config["general"]["version"]


def get_plugin_version():
    version = plugin_version()
    return "Plugin/" + version + " QGIS/" + get_qgis_version_str()


def is_versioned_file(file):
    """ Check if file is compatible with geodiff lib and hence suitable for versioning.

    :param file: file path
    :type file: str
    :returns: if file is compatible with geodiff lib
    :rtype: bool
    """
    diff_extensions = ['.gpkg', '.sqlite']
    f_extension = os.path.splitext(file)[1]
    return f_extension in diff_extensions


def send_logs(username, logfile):
    """ Send mergin-client logs to dedicated server

    :param logfile: path to logfile
    :returns: name of submitted file, error message
    """
    mergin_url, _, _ = get_mergin_auth()
    system = platform.system().lower()
    version = plugin_version()

    params = {
        "app": "plugin-{}-{}".format(system, version),
        "username": username
    }
    url = MERGIN_LOGS_URL + "?" + urllib.parse.urlencode(params)
    header = {"content-type": "text/plain"}

    meta = "Plugin: {} \nQGIS: {} \nSystem: {} \nMergin URL: {} \nMergin user: {} \n--------------------------------\n"\
        .format(
            version,
            get_qgis_version_str(),
            system,
            mergin_url,
            username
        )

    with open(logfile, 'rb') as f:
        if os.path.getsize(logfile) > 512 * 1024:
            f.seek(-512 * 1024, os.SEEK_END)
        logs = f.read()

    payload = meta.encode() + logs
    try:
        req = urllib.request.Request(url, data=payload, headers=header)
        resp = urllib.request.urlopen(req)
        log_file_name = resp.read().decode()
        if resp.msg != 'OK':
            return None, str(resp.reason)
        return log_file_name, None
    except (HTTPError, URLError) as e:
        return None, str(e)


def validate_mergin_url(url):
    """
    Validation of mergin URL by pinging. Checks if URL points at compatible Mergin server.
    :param url: String Mergin URL to ping.
    :return: String error message as result of validation. If None, URL is valid.
    """
    try:
        mc = MerginClient(url)
        if not mc.is_server_compatible():
            return 'Incompatible Mergin server'
    # Valid but not Mergin URl
    except ClientError:
        return "Invalid Mergin URL"
    # Cannot parse URL
    except ValueError:
        return "Invalid URL"
    return None


def proj_local_path(project_name):
    """Check if project was downloaded and return its path."""
    s = QSettings()
    proj_path = s.value(f"Mergin/localProjects/{project_name}/path", None)
    # check local project dir was not unintentionally removed
    if proj_path:
        if not os.path.exists(proj_path):
            proj_path = None
    return proj_path
