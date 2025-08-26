# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited


import os

from qgis.PyQt.QtGui import QIcon

from qgis.core import QgsProcessingProvider

from ..utils import mm_symbol_path
from .algs.create_report import CreateReport
from .algs.extract_local_changes import ExtractLocalChanges
from .algs.create_diff import CreateDiff
from .algs.download_vector_tiles import DownloadVectorTiles


class MerginProvider(QgsProcessingProvider):
    def __init__(self):
        super().__init__()
        self.algs = []

    def id(self):
        return "mergin"

    def name(self):
        return "Mergin Maps"

    def icon(self):
        return QIcon(mm_symbol_path())

    def load(self):
        self.refreshAlgorithms()
        return True

    def unload(self):
        pass

    def supportsNonFileBasedOutput(self):
        return False

    def getAlgs(self):
        algs = [
            CreateReport(),
            ExtractLocalChanges(),
            CreateDiff(),
            DownloadVectorTiles(),
        ]

        return algs

    def loadAlgorithms(self):
        self.algs = self.getAlgs()
        for a in self.algs:
            self.addAlgorithm(a)
