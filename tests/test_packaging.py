# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited


import os
import tempfile
from pathlib import Path

from qgis.core import QgsProviderRegistry, QgsRasterLayer, QgsVectorTileLayer

from Mergin.utils import package_layer

test_data_path = os.path.join(os.path.dirname(__file__), "data")


def test_copy_raster(dem_tif_path: Path):
    """Test packaging of raster layer and updating data source."""

    layer = QgsRasterLayer(dem_tif_path.as_posix(), "test", "gdal")

    assert layer.isValid()

    source_raster_uri = layer.dataProvider().dataSourceUri()

    assert source_raster_uri == dem_tif_path.as_posix()

    with tempfile.TemporaryDirectory() as tmp_dir:
        package_layer(layer, tmp_dir)
        for ext in ("tif", "wld", "tfw", "prj", "qpj", "tifw"):
            expected_filepath = Path(tmp_dir) / f"dem.{ext}"
            assert expected_filepath.exists()

            if ext == "tif":
                # Check if raster data source was updated
                destination_raster_uri = layer.dataProvider().dataSourceUri()
                assert destination_raster_uri == expected_filepath.as_posix()


def test_mbtiles_packaging_raster_layer(raster_tiles_path: Path):
    """Test packaging of raster and vector tiles layers and updating data source."""

    rlayer = QgsRasterLayer(f"url=file://{raster_tiles_path.as_posix()}&type=mbtiles", "test", "wms")

    assert rlayer.isValid()

    with tempfile.TemporaryDirectory() as tmp_dir:
        package_layer(rlayer, tmp_dir)
        expected_path = Path(tmp_dir) / "raster-tiles.mbtiles"
        assert expected_path.exists()

        uri = QgsProviderRegistry.instance().decodeUri("wms", rlayer.source())
        assert str(uri)
        assert "path" in uri
        assert uri["path"] == expected_path.as_posix()


def test_mbtiles_packaging_vector_tile_layer(vector_tiles_path: Path):

    vlayer = QgsVectorTileLayer(f"url=file://{vector_tiles_path.as_posix()}&type=mbtiles", "test")
    assert vlayer.isValid()

    with tempfile.TemporaryDirectory() as tmp_dir:
        package_layer(vlayer, tmp_dir)
        expected_path = Path(tmp_dir) / "vector-tiles.mbtiles"

        assert expected_path.exists()

        uri = QgsProviderRegistry.instance().decodeUri("vectortile", vlayer.source())
        assert "path" in uri
        assert uri["path"] == expected_path.as_posix()
