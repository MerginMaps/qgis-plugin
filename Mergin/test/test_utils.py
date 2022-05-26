# -*- coding: utf-8 -*-

import os
import json
import copy

from qgis.testing import start_app, unittest
from Mergin.utils import same_schema

test_data_path = os.path.join(os.path.dirname(__file__), 'data')


class test_utils(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        start_app()

    def tearDown(self):
        del(self.base_schema)
        del(self.tables_schema)

    def setUp(self):
        with open(os.path.join(test_data_path, 'schema_base.json')) as f:
            self.base_schema = json.load(f).get('geodiff_schema')

        with open(os.path.join(test_data_path, 'schema_two_tables.json')) as f:
            self.tables_schema = json.load(f).get('geodiff_schema')

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


if __name__ == '__main__':
    nose2.main()
