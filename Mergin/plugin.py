# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited

from qgis.core import *


class MerginPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.menu = u'Mergin Plugin'

    def initGui(self):
        pass

    def unload(self):
        pass
