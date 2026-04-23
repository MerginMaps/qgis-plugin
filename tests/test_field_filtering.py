# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited


import json
from pathlib import Path

import pytest
from qgis.core import QgsVectorLayer, QgsProject, QgsVectorFileWriter
from Mergin.field_filtering import (
    FieldFilter,
    FieldFilterModel,
    FieldFilterType,
    SQL_PLACEHOLDER_VALUE,
    SQL_PLACEHOLDER_VALUE_FROM,
    SQL_PLACEHOLDER_VALUE_TO,
    field_filters_from_json,
    field_filters_to_json,
    excluded_layers_list,
)


# -----------------------------------------------------------------------------
# TestFieldFilter
# -----------------------------------------------------------------------------


def test_init_sets_attributes(layer_field_filter: QgsVectorLayer):
    """Test that the constructor sets all attributes correctly."""
    f = FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "Text Filter")

    assert f.layer_id == layer_field_filter.id()
    assert f.provider == "ogr"
    assert f.field_name == "attr_string"
    assert f.filter_type == FieldFilterType.TEXT
    assert f.filter_name == "Text Filter"


def test_init_raises_for_nonexistent_field(layer_field_filter: QgsVectorLayer):
    """Test that the constructor raises a ValueError if the specified field does not exist."""
    with pytest.raises(ValueError):
        FieldFilter(layer_field_filter, "nonexistent_field", FieldFilterType.TEXT, "Text Filter")


def test_to_dict(layer_field_filter: QgsVectorLayer):
    """Test that to_dict produces the expected dictionary representation with proper values."""
    f = FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "My Filter")
    data = f.to_dict()

    assert set(data.keys()) == {
        "layer_id",
        "provider",
        "field_name",
        "filter_type",
        "filter_name",
        "sql_expression",
    }  # noqa: E501
    assert data["field_name"] == "attr_string"
    assert data["filter_type"] == "Text"
    assert data["filter_name"] == "My Filter"
    assert data["provider"] == "ogr"
    assert data["layer_id"] == layer_field_filter.id()

    f2 = FieldFilter(layer_field_filter, "attr_double", FieldFilterType.NUMBER, "My Filter 2")
    data2 = f2.to_dict()

    assert data2["field_name"] == "attr_double"
    assert data2["filter_type"] == "Number"
    assert data2["filter_name"] == "My Filter 2"


def test_from_dict_roundtrip(layer_field_filter: QgsVectorLayer):
    """Test that from_dict can restore an instance from the dictionary produced by to_dict."""
    original = FieldFilter(layer_field_filter, "attr_bool", FieldFilterType.CHECKBOX, "Bool")
    restored = FieldFilter.from_dict(original.to_dict())

    assert restored == original


# -----------------------------------------------------------------------------
# SQL expression — OGR provider
# -----------------------------------------------------------------------------


def test_text_ogr(layer_field_filter: QgsVectorLayer):
    f = FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "Text")
    assert f.sql_expression == f"CAST(\"attr_string\" AS CHARACTER) LIKE '%{SQL_PLACEHOLDER_VALUE}%'"


def test_number_ogr(layer_field_filter: QgsVectorLayer):
    f = FieldFilter(layer_field_filter, "attr_double", FieldFilterType.NUMBER, "Number")
    assert f.sql_expression == (
        f'CAST("attr_double" AS FLOAT) >= {SQL_PLACEHOLDER_VALUE_FROM} '
        f'AND CAST("attr_double" AS FLOAT) <= {SQL_PLACEHOLDER_VALUE_TO}'
    )


def test_date_ogr(layer_field_filter: QgsVectorLayer):
    f = FieldFilter(layer_field_filter, "attr_date", FieldFilterType.DATE, "Date")
    assert f.sql_expression == (
        f"CAST(\"attr_date\" AS CHARACTER) >= '{SQL_PLACEHOLDER_VALUE_FROM}' "
        f"AND CAST(\"attr_date\" AS CHARACTER) <= '{SQL_PLACEHOLDER_VALUE_TO}'"
    )


def test_checkbox_ogr(layer_field_filter: QgsVectorLayer):
    f = FieldFilter(layer_field_filter, "attr_bool", FieldFilterType.CHECKBOX, "Bool")
    assert f.sql_expression == f'"attr_bool" = {SQL_PLACEHOLDER_VALUE}'


def test_single_select_ogr(layer_field_filter: QgsVectorLayer):
    f = FieldFilter(layer_field_filter, "attr_string", FieldFilterType.SINGLE_SELECT, "Single")
    assert f.sql_expression == f'"attr_string" IS {SQL_PLACEHOLDER_VALUE}'


def test_multi_select_ogr(layer_field_filter: QgsVectorLayer):
    f = FieldFilter(layer_field_filter, "attr_string", FieldFilterType.MULTI_SELECT, "Multi")
    assert f.sql_expression == f'"attr_string" IS {SQL_PLACEHOLDER_VALUE}'


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------


def test_to_json_produces_valid_json(layer_field_filter: QgsVectorLayer):
    filters = [
        FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "Text"),
        FieldFilter(layer_field_filter, "attr_double", FieldFilterType.NUMBER, "Number"),
    ]
    parsed = json.loads(field_filters_to_json(filters))

    assert len(parsed) == 2
    assert parsed[0]["filter_name"] == "Text"
    assert parsed[1]["filter_name"] == "Number"


def test_from_json_roundtrip(layer_field_filter: QgsVectorLayer):
    filters = [
        FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "Text"),
        FieldFilter(layer_field_filter, "attr_bool", FieldFilterType.CHECKBOX, "Bool"),
    ]
    restored = field_filters_from_json(field_filters_to_json(filters))

    assert len(restored) == 2
    assert restored[0].field_name == "attr_string"
    assert restored[1].filter_type == FieldFilterType.CHECKBOX


# -----------------------------------------------------------------------------
# FieldFilterModel
# -----------------------------------------------------------------------------


def test_model_add_filter(layer_field_filter: QgsVectorLayer):
    model = FieldFilterModel()
    model.add_filter(FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "My Filter"))

    assert model.rowCount() == 1


def test_model_remove_filter(layer_field_filter: QgsVectorLayer):
    model = FieldFilterModel()
    model.add_filter(FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "A"))
    model.add_filter(FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "B"))

    model.remove_filter(0)

    assert model.rowCount() == 1
    assert model.filter_names() == ["B"]


def test_model_remove_filter_out_of_range(layer_field_filter: QgsVectorLayer):
    model = FieldFilterModel()
    model.add_filter(FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "My Filter"))

    model.remove_filter(5)  # no-op, should not raise

    assert model.rowCount() == 1


def test_model_move(layer_field_filter: QgsVectorLayer):
    model = FieldFilterModel()
    model.add_filter(FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "A"))
    model.add_filter(FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "B"))
    model.add_filter(FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "C"))

    # move A one step down
    model.move_filter(0, 1)

    assert model.filter_names() == ["B", "A", "C"]

    # move A one step up
    model.move_filter(1, -1)

    assert model.filter_names() == ["A", "B", "C"]

    # target index 3 is out of range - do nothing
    model.move_filter(2, 1)

    assert model.filter_names() == ["A", "B", "C"]


def test_model_filter_names(layer_field_filter: QgsVectorLayer):
    model = FieldFilterModel()
    for name in ("First", "Second", "Third"):
        model.add_filter(FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, name))

    assert model.filter_names() == ["First", "Second", "Third"]


def test_model_json_roundtrip(layer_field_filter: QgsVectorLayer):
    model = FieldFilterModel()
    model.add_filter(FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "Text"))
    model.add_filter(FieldFilter(layer_field_filter, "attr_double", FieldFilterType.NUMBER, "Number"))

    model2 = FieldFilterModel()
    model2.load_from_json(model.to_json())

    assert model2.filter_names() == ["Text", "Number"]


def test_model_replace_filter(layer_field_filter: QgsVectorLayer):
    model = FieldFilterModel()
    model.add_filter(FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "Original"))
    model.add_filter(FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "Other"))

    model.replace_filter(0, FieldFilter(layer_field_filter, "attr_double", FieldFilterType.NUMBER, "Replaced"))

    assert model.rowCount() == 2
    assert model.filter_names() == ["Replaced", "Other"]

    # out of range - do nothing
    model.replace_filter(5, FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "B"))  # no-op

    assert model.filter_names() == ["Replaced", "Other"]


def test_model_load_from_json_replaces_existing(layer_field_filter: QgsVectorLayer):
    model = FieldFilterModel()
    model.add_filter(FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "Old"))

    new_filters = [FieldFilter(layer_field_filter, "attr_string", FieldFilterType.TEXT, "New")]
    model.load_from_json(field_filters_to_json(new_filters))

    assert model.filter_names() == ["New"]


def test_excluded_layers_list(layer_field_filter: QgsVectorLayer, mem_layer: QgsVectorLayer, tmp_path: Path):

    # create geojson and shp layers for test
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GeoJSON"

    path_geojson_ = tmp_path / "layer.geojson"

    error, _, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
        mem_layer,
        path_geojson_.as_posix(),
        QgsProject.instance().transformContext(),
        options,
    )

    assert error == QgsVectorFileWriter.WriterError.NoError

    layer_geojson = QgsVectorLayer(path_geojson_.as_posix(), "geojson", "ogr")
    assert layer_geojson.isValid()

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "ESRI Shapefile"

    path_shp = tmp_path / "layer.shp"

    error, _, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
        mem_layer,
        path_shp.as_posix(),
        QgsProject.instance().transformContext(),
        options,
    )

    assert error == QgsVectorFileWriter.WriterError.NoError

    layer_shp = QgsVectorLayer(path_shp.as_posix(), "shapefile", "ogr")
    assert layer_shp.isValid()

    # test that GPKG layer is not excluded
    QgsProject.instance().addMapLayer(layer_field_filter)
    excluded_layers = excluded_layers_list()
    assert len(excluded_layers) == 0
    assert layer_field_filter not in excluded_layers

    # add layers to project
    QgsProject.instance().addMapLayer(layer_geojson)
    QgsProject.instance().addMapLayer(layer_shp)

    # test that non-GPKG layers are excluded
    excluded_layers = excluded_layers_list()
    assert len(excluded_layers) == 2
    assert layer_geojson in excluded_layers
    assert layer_shp in excluded_layers
    assert layer_field_filter not in excluded_layers
