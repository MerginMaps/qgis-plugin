# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited

import json
from pathlib import Path
from typing import Dict

import pytest
from qgis.core import QgsProject, QgsVectorLayer


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


@pytest.fixture
def base_schema(test_data_path: Path) -> Dict:
    """Fixture for base schema used in tests."""
    with open(test_data_path / "schema_base.json") as f:
        return json.load(f).get("geodiff_schema")


@pytest.fixture
def tables_schema(test_data_path: Path) -> Dict:
    """Fixture for tables schema used in tests."""
    with open(test_data_path / "schema_two_tables.json") as f:
        return json.load(f).get("geodiff_schema")


@pytest.fixture
def project_dir(mem_layer: QgsVectorLayer, tmp_path: Path) -> Path:
    """Fixture for a QGIS project directory."""
    proj = QgsProject.instance()
    proj.addMapLayer(mem_layer)
    proj.setFileName(str(tmp_path / "test_project.qgz"))
    yield tmp_path
    proj.removeMapLayer(mem_layer.id())


@pytest.fixture
def layer_field_filter(test_data_path: Path) -> QgsVectorLayer:
    """Fixture for the field filter test layer."""
    layer = QgsVectorLayer(str(test_data_path / "data_field_filter.gpkg"), "field filter layer", "ogr")
    assert layer.isValid()
    return layer
