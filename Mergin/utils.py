import os
from datetime import datetime, timezone
from urllib.error import URLError
from qgis.core import (
    QgsApplication,
    QgsAuthMethodConfig
)
from qgis.PyQt.QtCore import QSettings

try:
    from .mergin.client import MerginClient, ClientError, InvalidProject
except ImportError:
    import sys
    this_dir = os.path.dirname(os.path.realpath(__file__))
    path = os.path.join(this_dir, 'mergin_client.whl')
    sys.path.append(path)
    from mergin.client import MerginClient, ClientError, InvalidProject


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
    settings = QSettings()
    auth_token = settings.value('Mergin/auth_token', None)
    if auth_token:
        mc = MerginClient(url, auth_token)
        # check token expiration
        delta = mc._auth_session['expire'] - datetime.now(timezone.utc)
        if delta.total_seconds() > 1:
            return mc

    try:
        mc = MerginClient(url, None, username, password)
    except (URLError, ClientError):
        raise 
    settings.setValue('Mergin/auth_token', mc._auth_session['token'])
    return MerginClient(url, mc._auth_session['token'])


def changes_from_metadata(metadata):
    added = ", ".join(f['path'] for f in metadata['added'])
    removed = ", ".join(f['path'] for f in metadata['removed'])
    updated = ", ".join(f['path'] for f in metadata['updated'])
    renamed = ", ".join(f"{f['path']} -> {f['new_path']}" for f in metadata['renamed'])
    return added, removed, updated, renamed
