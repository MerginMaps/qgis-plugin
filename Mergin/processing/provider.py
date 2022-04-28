# -*- coding: utf-8 -*-

import os

from qgis.PyQt.QtGui import QIcon

from qgis.core import QgsProcessingProvider

from ..utils import icon_path
from .algs.create_report import CreateReport


class MerginProvider(QgsProcessingProvider):

    def __init__(self):
        super().__init__()
        self.algs = []

    def id(self):
        return 'mergin'

    def name(self):
        return 'Mergin Maps'

    def icon(self):
        return QIcon(icon_path('mm_icon_positive.png', False))

    def load(self):
        self.refreshAlgorithms()
        return True

    def unload(self):
        pass

    def supportsNonFileBasedOutput(self):
        return False

    def getAlgs(self):
        algs = [CreateReport(),
               ]

        return algs

    def loadAlgorithms(self):
        self.algs = self.getAlgs()
        for a in self.algs:
            self.addAlgorithm(a)
