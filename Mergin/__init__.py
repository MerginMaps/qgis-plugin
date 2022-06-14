# GPLv3 license
# Copyright Lutra Consulting Limited


def classFactory(iface):
    from .plugin import MerginPlugin

    return MerginPlugin(iface)
