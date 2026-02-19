# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited


import os
import urllib.request
from qgis.core import (
    QgsVectorLayer,
)
from qgis.testing import start_app, unittest
from Mergin.help import MerginHelp

test_data_path = os.path.join(os.path.dirname(__file__), "data")


class test_help(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start_app()

    def test_help_urls(self):
        mh = MerginHelp()

        req = urllib.request.Request(mh.howto_attachment_widget(), method="HEAD")
        resp = urllib.request.urlopen(req)
        self.assertEqual(resp.status, 200)

        req = urllib.request.Request(mh.howto_background_maps(), method="HEAD")
        resp = urllib.request.urlopen(req)
        self.assertEqual(resp.status, 200)


def create_mem_layer() -> QgsVectorLayer:
    """
    Create a memory layer.
    """
    layer = QgsVectorLayer("Point", "test", "memory")

    return layer


if __name__ == "__main__":
    nose2.main()
