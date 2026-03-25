# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited

from pathlib import Path

import pytest
from qgis.core import QgsVectorLayer


@pytest.fixture
def test_data_path() -> Path:
    """Fixture for test data path."""
    return Path(__file__).parent / "data"


@pytest.fixture
def mem_layer() -> QgsVectorLayer:
    """Fixture for an in-memory vector layer."""
    return QgsVectorLayer("Point", "test", "memory")


@pytest.fixture
def dem_tif_path(test_data_path: Path) -> Path:
    """Fixture for DEM TIFF file path."""
    return test_data_path / "dem.tif"


@pytest.fixture
def raster_tiles_path(test_data_path: Path) -> Path:
    """Fixture for raster tiles MBTiles file path."""
    return test_data_path / "raster-tiles.mbtiles"


@pytest.fixture
def vector_tiles_path(test_data_path: Path) -> Path:
    """Fixture for vector tiles MBTiles file path."""
    return test_data_path / "vector-tiles.mbtiles"
