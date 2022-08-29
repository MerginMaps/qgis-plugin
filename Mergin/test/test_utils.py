# -*- coding: utf-8 -*-

import os
import json
import copy

from qgis.core import (
    QgsProject,
    QgsDatumTransform,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
)

from qgis.testing import start_app, unittest
from Mergin.utils import same_schema, get_datum_shift_grids

test_data_path = os.path.join(os.path.dirname(__file__), "data")


class test_utils(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start_app()

    def tearDown(self):
        del self.base_schema
        del self.tables_schema

    def setUp(self):
        with open(os.path.join(test_data_path, "schema_base.json")) as f:
            self.base_schema = json.load(f).get("geodiff_schema")

        with open(os.path.join(test_data_path, "schema_two_tables.json")) as f:
            self.tables_schema = json.load(f).get("geodiff_schema")

    def test_table_added_removed(self):
        equal, msg = same_schema(self.base_schema, self.base_schema)
        self.assertTrue(equal)
        self.assertEqual(msg, "No schema changes")

        equal, msg = same_schema(self.base_schema, self.tables_schema)
        self.assertFalse(equal)
        self.assertEqual(msg, "Tables added/removed: added: hotels")

        equal, msg = same_schema(self.tables_schema, self.base_schema)
        self.assertFalse(equal)
        self.assertEqual(msg, "Tables added/removed: removed: hotels")

    def test_table_schema_changed(self):
        modified_schema = copy.deepcopy(self.base_schema)

        # change column name from fid to id
        modified_schema[0]["columns"][0]["name"] = "id"
        equal, msg = same_schema(self.base_schema, modified_schema)
        self.assertFalse(equal)
        self.assertEqual(msg, "Fields in table 'Survey_points' added/removed: added: id; removed: fid")
        modified_schema[0]["columns"][0]["name"] = "fid"

        # change column type from datetime to date
        modified_schema[0]["columns"][2]["type"] = "date"
        equal, msg = same_schema(self.base_schema, modified_schema)
        self.assertFalse(equal)
        self.assertEqual(msg, "Definition of 'date' field in 'Survey_points' table is not the same")

    def test_datum_shift_grids(self):
        grids = get_datum_shift_grids()
        self.assertEqual(len(grids), 0)

        crs_a = QgsCoordinateReferenceSystem("EPSG:27700")
        crs_b = QgsCoordinateReferenceSystem("EPSG:3857")
        ops = QgsDatumTransform.operations(crs_a, crs_b)
        self.assertTrue(len(ops) > 0)
        proj_str = ops[0].proj

        context = QgsCoordinateTransformContext()
        context.addCoordinateOperation(crs_a, crs_b, proj_str)
        QgsProject.instance().setTransformContext(context)

        # if there are no layers which use datum transformtaions nothing
        # should be returned
        grids = get_datum_shift_grids()
        self.assertEqual(len(grids), 0)

        layer = QgsVectorLayer("Point?crs=EPSG:27700", "", "memory")
        QgsProject.instance().addMapLayer(layer)
        QgsProject.instance().setCrs(crs_b)

        grids = get_datum_shift_grids()
        self.assertEqual(len(grids), 1)
        self.assertTrue("uk_os_OSTN15_NTv2_OSGBtoETRS.tif" in grids or "OSTN15_NTv2_OSGBtoETRS.gsb" in grids)


if __name__ == "__main__":
    nose2.main()
