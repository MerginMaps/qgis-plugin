import os
from urllib.error import URLError, HTTPError
from .client import MerginClient


def auth_ok(url, username, password):
    """ Temporary auth check on server. """
    mc = MerginClient(url, username, password)
    try:
        mc.get('/auth/user/{}'.format(username))
    except HTTPError as err:
        # desired testing exception saying that auth is correct
        if err.code == 403:
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
