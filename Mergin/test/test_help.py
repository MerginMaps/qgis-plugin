# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited


import os
import requests
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

        resp = requests.head(mh.howto_attachment_widget(), timeout=5, allow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        resp = requests.head(mh.howto_background_maps(), timeout=5, allow_redirects=True)
        self.assertEqual(resp.status_code, 200)


def create_mem_layer() -> QgsVectorLayer:
    """
    Create a memory layer.
    """
    layer = QgsVectorLayer("Point", "test", "memory")

    return layer


if __name__ == "__main__":
    nose2.main()  # noqa: F821
