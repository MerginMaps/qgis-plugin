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
