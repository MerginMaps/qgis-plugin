import os
from urllib.error import URLError, HTTPError
from .client import MerginClient, ClientError


def auth_ok(url, username, password):
    """ Temporary auth check on server. """
    mc = MerginClient(url, username, password)
    try:
        mc.get('/auth/user/{}'.format(username))
    except ClientError as err:
        try:
            err.args[0].decode('utf-8')
            return False
        except AttributeError:
            pass
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
