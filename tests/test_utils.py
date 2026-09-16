# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited


import copy
import tempfile
from pathlib import Path
from typing import Dict

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsDatumTransform,
    QgsProject,
    QgsSymbolLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from Mergin.utils import (
    create_map_sketches_layer,
    create_tracking_layer,
    get_datum_shift_grids,
    is_valid_name,
    same_schema,
)


def test_table_added_removed(base_schema: Dict, tables_schema: Dict):
    equal, msg = same_schema(base_schema, base_schema)
    assert equal
    assert msg == "No schema changes"

    equal, msg = same_schema(base_schema, tables_schema)
    assert not equal
    assert msg == "Tables added/removed: added: hotels"

    equal, msg = same_schema(tables_schema, base_schema)
    assert not equal
    assert msg == "Tables added/removed: removed: hotels"


def test_table_schema_changed(base_schema: Dict):
    modified_schema = copy.deepcopy(base_schema)

    # change column name from fid to id
    modified_schema[0]["columns"][0]["name"] = "id"
    equal, msg = same_schema(base_schema, modified_schema)
    assert not equal
    assert msg == "Fields in table 'Survey_points' added/removed: added: id; removed: fid"
    modified_schema[0]["columns"][0]["name"] = "fid"

    # change column type from datetime to date
    modified_schema[0]["columns"][2]["type"] = "date"
    equal, msg = same_schema(base_schema, modified_schema)
    assert not equal
    assert msg == "Definition of 'date' field in 'Survey_points' table is not the same"


def test_datum_shift_grids():
    grids = get_datum_shift_grids()
    assert len(grids) == 0

    crs_a = QgsCoordinateReferenceSystem("EPSG:27700")
    crs_b = QgsCoordinateReferenceSystem("EPSG:3857")
    ops = QgsDatumTransform.operations(crs_a, crs_b)
    assert len(ops) > 0
    proj_str = ops[0].proj

    context = QgsCoordinateTransformContext()
    context.addCoordinateOperation(crs_a, crs_b, proj_str)
    QgsProject.instance().setTransformContext(context)

    # if there are no layers which use datum transformations nothing should be returned
    grids = get_datum_shift_grids()
    assert len(grids) == 0

    layer = QgsVectorLayer("Point?crs=EPSG:27700", "", "memory")
    QgsProject.instance().addMapLayer(layer)
    QgsProject.instance().setCrs(crs_b)

    grids = get_datum_shift_grids()
    assert len(grids) == 1
    assert "uk_os_OSTN15_NTv2_OSGBtoETRS.tif" in grids or "OSTN15_NTv2_OSGBtoETRS.gsb" in grids

    QgsProject.instance().removeMapLayer(layer.id())


def test_name_validation():
    test_cases = [
        ("project", True),
        ("ProJect", True),
        ("Pro123ject", True),
        ("123PROJECT", True),
        ("PROJECT", True),
        ("project ", True),
        ("pro ject", True),
        ("proj-ect", True),
        ("-project", True),
        ("proj_ect", True),
        ("proj.ect", True),
        ("proj!ect", True),
        (" project", False),
        (".project", False),
        ("proj~ect", False),
        (r"pro\ject", False),
        ("pro/ject", False),
        ("pro|ject", False),
        ("pro+ject", False),
        ("pro=ject", False),
        ("pro>ject", False),
        ("pro<ject", False),
        ("pro@ject", False),
        ("pro#ject", False),
        ("pro$ject", False),
        ("pro%ject", False),
        ("pro^ject", False),
        ("pro&ject", False),
        ("pro*ject", False),
        ("pro?ject", False),
        ("pro:ject", False),
        ("pro;ject", False),
        ("pro,ject", False),
        ("pro`ject", False),
        ("pro'ject", False),
        ('pro"ject', False),
        ("projectz", True),
        ("projectZ", True),
        ("project0", True),
        ("pro(ject", False),
        ("pro)ject", False),
        ("pro{ject", False),
        ("pro}ject", False),
        ("pro[ject", False),
        ("pro]ject", False),
        ("pro]ject", False),
        ("CON", False),
        ("NUL", False),
        ("NULL", True),
        ("PRN", False),
        ("LPT0", False),
        ("lpt0", False),
        ("LPT1", False),
        ("lpt1", False),
        ("COM1", False),
        ("com1", False),
        ("AUX", False),
        ("AuX", False),
        ("projAUXect", True),
        ("CONproject", True),
        ("projectCON", True),
        ("support", False),
        ("helpdesk", False),
        ("input", False),
        ("lutraconsulting", False),
        ("lutra", False),
        ("merginmaps", False),
        ("mergin", False),
        ("admin", False),
        ("sales", False),
        ("測試", True),
        ("מִבְחָן", True),
        ("", False),
    ]

    for name, expected in test_cases:
        assert is_valid_name(name) == expected


def test_create_tracking_layer():
    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = create_tracking_layer(temp_dir)

        assert Path(file_path).exists()
        assert Path(file_path).name == "tracking_layer.gpkg"

        layer = QgsVectorLayer(file_path, "", "ogr")
        assert layer.isValid()
        assert layer.wkbType() == QgsWkbTypes.LineStringZM

        fields = layer.fields()
        assert len(fields) == 5
        assert fields[0].name() == "fid"
        assert fields[1].name() == "tracking_start_time"
        assert fields[1].type() == QVariant.DateTime
        assert fields[2].name() == "tracking_end_time"
        assert fields[2].type() == QVariant.DateTime
        assert fields[3].name() == "total_distance"
        assert fields[3].type() == QVariant.Double
        assert fields[4].name() == "tracked_by"
        assert fields[4].type() == QVariant.String


def test_create_map_sketches_layer():
    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = create_map_sketches_layer(temp_dir)

        assert Path(file_path).exists()
        assert Path(file_path).name == "map_sketches.gpkg"

        layer = QgsProject.instance().mapLayersByName("Map sketches")[0]

        assert layer.isValid()
        assert layer.wkbType() == QgsWkbTypes.MultiLineStringZM

        fields = layer.fields()
        assert len(fields) == 9
        assert fields[0].name() == "fid"
        assert fields[1].name() == "color"
        assert fields[1].type() == QVariant.String
        assert fields[2].name() == "author"
        assert fields[2].type() == QVariant.String
        assert fields[3].name() == "created_at"
        assert fields[3].type() == QVariant.DateTime
        assert fields[4].name() == "width"
        assert fields[4].type() == QVariant.Double
        assert fields[5].name() == "attr1"
        assert fields[5].type() == QVariant.Double
        assert fields[6].name() == "attr2"
        assert fields[6].type() == QVariant.Double
        assert fields[7].name() == "attr3"
        assert fields[7].type() == QVariant.String
        assert fields[8].name() == "attr4"
        assert fields[8].type() == QVariant.String

        sl = layer.renderer().symbol().symbolLayer(0)
        assert sl.dataDefinedProperties().property(QgsSymbolLayer.PropertyStrokeColor).expressionString() == '"color"'
        assert sl.dataDefinedProperties().property(QgsSymbolLayer.PropertyStrokeWidth).expressionString() == '"width"'
