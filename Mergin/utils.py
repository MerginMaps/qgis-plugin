import os
from urllib.error import URLError
from qgis.core import (
    QgsApplication,
    QgsAuthMethodConfig
)
from qgis.PyQt.QtCore import QSettings

try:
    from .mergin.client import MerginClient, ClientError
except ImportError:
    import sys
    this_dir = os.path.dirname(os.path.realpath(__file__))
    path = os.path.join(this_dir, 'mergin_client.whl')
    sys.path.append(path)
    from mergin.client import MerginClient, ClientError


def auth_ok(url, username, password):
    """ Temporary auth check on server. """
    mc = MerginClient(url, username, password)
    try:
        mc.get('/auth/user/{}'.format(username))
    except ClientError as err:
        # desired testing exception saying that auth is correct
        if "You don't have the permission to access the requested resource" in err.args[0]:
            return True
        else:
            return False
    except (URLError, ValueError):
        return False
    return True


def find_qgis_files(directory):
    qgis_files = []
    for root, dirs, files in os.walk(directory):
        for f in files:
            _, ext = os.path.splitext(f)
            if ext in ['.qgs', '.qgz']:
                qgis_files.append(os.path.join(root, f))           
    return qgis_files


def find_local_conflicts(directory):
    conflict_files = []
    for root, dirs, files in os.walk(directory):
        for f in files:
            if '_conflict_copy' in f:
                conflict_files.append(os.path.join(root, f))
    return conflict_files


def get_mergin_auth():
    settings = QSettings()
    authcfg = settings.value('Mergin/authcfg', None)
    auth_manager = QgsApplication.authManager()
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


def create_mergin_client():
    url, username, password = get_mergin_auth()
    mc = MerginClient(url, username, password)
    return mc
