# GPLv3 license
# Copyright Lutra Consulting Limited

try:
    from .mergin.client import MerginClient
except ImportError:
    import os
    import sys
    this_dir = os.path.dirname(os.path.realpath(__file__))
    path = os.path.join(this_dir, 'mergin_client-dev-py3-none-any.whl')
    sys.path.append(path)


def classFactory(iface):
    from .plugin import MerginPlugin
    return MerginPlugin(iface)
