# -*- coding: utf-8 -*-

import os
import tempfile

from qgis.core import QgsRasterLayer, QgsVectorTileLayer, QgsProviderRegistry

from qgis.testing import start_app, unittest
from Mergin.utils import package_layer

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
        self.assertEqual(source_raster_uri, test_data_raster_path)
        with tempfile.TemporaryDirectory() as tmp_dir:
            package_layer(layer, tmp_dir)
            for ext in ("tif", "wld", "tfw", "prj", "qpj", "tifw"):
                expected_filepath = os.path.join(tmp_dir, f"dem.{ext}")
                self.assertTrue(os.path.exists(expected_filepath))
                if ext == "tif":
                    # Check if raster data source was updated
                    destination_raster_uri = layer.dataProvider().dataSourceUri()
                    self.assertEqual(destination_raster_uri, expected_filepath)

    def test_mbtiles_packaging(self):
        raster_tiles_path = os.path.join(test_data_path, "raster-tiles.mbtiles")
        layer = QgsRasterLayer(f"url=file://{raster_tiles_path}&type=mbtiles", "test", "wms")
        self.assertTrue(layer.isValid())
        with tempfile.TemporaryDirectory() as tmp_dir:
            package_layer(layer, tmp_dir)
            expected_path = os.path.join(tmp_dir, "raster-tiles.mbtiles")
            self.assertTrue(os.path.exists(expected_path))
            uri = QgsProviderRegistry.instance().decodeUri("wms", layer.source())
            self.assertTrue("path" in uri, str(uri))
            self.assertEqual(uri["path"], expected_path)

        vector_tiles_path = os.path.join(test_data_path, "vector-tiles.mbtiles")
        layer = QgsVectorTileLayer(f"url={vector_tiles_path}&type=mbtiles", "test")
        self.assertTrue(layer.isValid())
        with tempfile.TemporaryDirectory() as tmp_dir:
            package_layer(layer, tmp_dir)
            expected_path = os.path.join(tmp_dir, "vector-tiles.mbtiles")
            self.assertTrue(os.path.exists(expected_path))
            uri = QgsProviderRegistry.instance().decodeUri("vectortile", layer.source())
            self.assertTrue("path" in uri)
            self.assertEqual(uri["path"], expected_path)


if __name__ == "__main__":
    nose2.main()
