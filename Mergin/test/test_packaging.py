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
        test_data_raster_path = os.path.join(test_data_path, "dem.tif")
        layer = QgsRasterLayer(test_data_raster_path, "test", "gdal")
        self.assertTrue(layer.isValid())
        source_raster_uri = layer.dataProvider().dataSourceUri()
        self.assertTrue(source_raster_uri == str(test_data_raster_path))
        with tempfile.TemporaryDirectory() as tmp_dir:
            copy_tif_raster(layer, tmp_dir)
            for ext in ("tif", "wld", "tfw", "prj", "qpj", "tifw"):
                expected_filepath = os.path.join(tmp_dir, f"dem.{ext}")
                self.assertTrue(os.path.exists(expected_filepath))
                if ext == "tif":
                    # Check if raster data source was updated
                    destination_raster_uri = layer.dataProvider().dataSourceUri()
                    self.assertTrue(destination_raster_uri == str(expected_filepath))
                    self.assertTrue(destination_raster_uri != source_raster_uri)


if __name__ == "__main__":
    nose2.main()
