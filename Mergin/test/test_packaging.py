# -*- coding: utf-8 -*-

import os
import tempfile

from qgis.core import QgsRasterLayer

from qgis.testing import start_app, unittest
from Mergin.utils import copy_tif_raster

test_data_path = os.path.join(os.path.dirname(__file__), "data")


class test_packaging(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start_app()

    def test_copy_raster(self):
        layer = QgsRasterLayer(os.path.join(test_data_path, "dem.tif"), "test", "gdal")
        self.assertTrue(layer.isValid())

        with tempfile.TemporaryDirectory() as tmp_dir:
            copy_tif_raster(layer, tmp_dir)
            for ext in ("tif", "wld", "tfw", "prj", "qpj", "tifw"):
                self.assertTrue(os.path.exists(os.path.join(tmp_dir, f"dem.{ext}")))


if __name__ == "__main__":
    nose2.main()
