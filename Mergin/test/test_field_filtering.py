# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited


import json
import os

import nose2

from qgis.core import QgsVectorLayer
from qgis.testing import start_app, unittest

from Mergin.field_filtering import (
    FieldFilter,
    FieldFilterModel,
    FieldFilterType,
    SQL_PLACEHOLDER_VALUE,
    SQL_PLACEHOLDER_VALUES,
    SQL_PLACEHOLDER_VALUE_FROM,
    SQL_PLACEHOLDER_VALUE_TO,
    field_filters_from_json,
    field_filters_to_json,
)

test_data_path = os.path.join(os.path.dirname(__file__), "data")


class _LayerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start_app()

    def setUp(self):
        layer_path = os.path.join(test_data_path, "data_field_filter.gpkg")
        self.layer = QgsVectorLayer(layer_path, "field filter layer", "ogr")
        self.assertTrue(self.layer.isValid())


class TestFieldFilter(_LayerTestCase):

    def test_init_sets_attributes(self):
        """Test that the constructor sets all attributes correctly."""
        f = FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "Text Filter")

        self.assertEqual(f.layer_id, self.layer.id())
        self.assertEqual(f.provider, "ogr")
        self.assertEqual(f.field_name, "attr_string")
        self.assertEqual(f.filter_type, FieldFilterType.TEXT)
        self.assertEqual(f.filter_name, "Text Filter")

    def test_init_raises_for_nonexistent_field(self):
        """Test that the constructor raises a ValueError if the specified field does not exist."""
        with self.assertRaises(ValueError):
            FieldFilter(self.layer, "nonexistent_field", FieldFilterType.TEXT, "Text Filter")

    def test_to_dict(self):
        """Test that to_dict produces the expected dictionary representation with proper values."""
        f = FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "My Filter")
        data = f.to_dict()

        self.assertEqual(
            set(data.keys()),
            {"layer_id", "provider", "field_name", "filter_type", "filter_name", "sql_expression"},
        )

        self.assertEqual(data["field_name"], "attr_string")
        self.assertEqual(data["filter_type"], "Text")
        self.assertEqual(data["filter_name"], "My Filter")
        self.assertEqual(data["provider"], "ogr")
        self.assertEqual(data["layer_id"], self.layer.id())

        f = FieldFilter(self.layer, "attr_double", FieldFilterType.NUMBER, "My Filter 2")
        data = f.to_dict()

        self.assertEqual(data["field_name"], "attr_double")
        self.assertEqual(data["filter_type"], "Number")
        self.assertEqual(data["filter_name"], "My Filter 2")

    def test_from_dict_roundtrip(self):
        """Test that from_dict can restore an instance from the dictionary produced by to_dict."""
        original = FieldFilter(self.layer, "attr_bool", FieldFilterType.CHECKBOX, "Bool")
        restored = FieldFilter.from_dict(original.to_dict())

        self.assertEqual(restored, original)


class TestFieldFilterSqlExpression(_LayerTestCase):

    def _postgres_filter(self, field_name: str, filter_type: FieldFilterType) -> FieldFilter:
        """Create a FieldFilter with a postgres provider, bypassing layer validation."""
        f = object.__new__(FieldFilter)
        f.layer_id = self.layer.id()
        f.provider = "postgres"
        f.field_name = field_name
        f.filter_type = filter_type
        f.filter_name = "test"
        f.sql_expression = ""
        f._generate_sql_expression()
        return f

    # -------------------------------------------------------------------------
    # ogr provider
    # -------------------------------------------------------------------------

    def test_text_ogr(self):
        f = FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "Text")
        self.assertEqual(f.sql_expression, f'CAST("attr_string" AS CHARACTER) LIKE {SQL_PLACEHOLDER_VALUE}')

    def test_number_ogr(self):
        f = FieldFilter(self.layer, "attr_double", FieldFilterType.NUMBER, "Number")
        self.assertEqual(
            f.sql_expression,
            f'CAST("attr_double" AS FLOAT) >= {SQL_PLACEHOLDER_VALUE_FROM} '
            f'AND CAST("attr_double" AS FLOAT) <= {SQL_PLACEHOLDER_VALUE_TO}',
        )

    def test_date_ogr(self):
        f = FieldFilter(self.layer, "attr_date", FieldFilterType.DATE, "Date")
        self.assertEqual(
            f.sql_expression,
            f'CAST("attr_date" AS DATE) >= {SQL_PLACEHOLDER_VALUE_FROM} '
            f'AND CAST("attr_date" AS DATE) <= {SQL_PLACEHOLDER_VALUE_TO}',
        )

    def test_checkbox_ogr(self):
        f = FieldFilter(self.layer, "attr_bool", FieldFilterType.CHECKBOX, "Bool")
        self.assertEqual(f.sql_expression, f'"attr_bool" = {SQL_PLACEHOLDER_VALUE}')

    def test_single_select_ogr(self):
        f = FieldFilter(self.layer, "attr_string", FieldFilterType.SINGLE_SELECT, "Single")
        self.assertEqual(f.sql_expression, f'"attr_string" = {SQL_PLACEHOLDER_VALUE}')

    def test_multi_select_ogr(self):
        f = FieldFilter(self.layer, "attr_string", FieldFilterType.MULTI_SELECT, "Multi")
        self.assertEqual(f.sql_expression, f'"attr_string" IN ({SQL_PLACEHOLDER_VALUES})')

    # -------------------------------------------------------------------------
    # postgres provider
    # -------------------------------------------------------------------------

    def test_text_postgres(self):
        f = self._postgres_filter("attr_string", FieldFilterType.TEXT)
        self.assertEqual(f.sql_expression, f'CAST("attr_string" AS text) ILIKE {SQL_PLACEHOLDER_VALUE}')

    def test_number_postgres(self):
        f = self._postgres_filter("attr_double", FieldFilterType.NUMBER)
        self.assertEqual(
            f.sql_expression,
            f'CAST("attr_double" AS numeric) >= {SQL_PLACEHOLDER_VALUE_FROM} '
            f'AND CAST("attr_double" AS numeric) <= {SQL_PLACEHOLDER_VALUE_TO}',
        )

    def test_date_postgres(self):
        f = self._postgres_filter("attr_date", FieldFilterType.DATE)
        self.assertEqual(
            f.sql_expression,
            f'CAST("attr_date" AS timestamp) >= {SQL_PLACEHOLDER_VALUE_FROM} '
            f'AND CAST("attr_date" AS timestamp) <= {SQL_PLACEHOLDER_VALUE_TO}',
        )


class TestFieldFilterHelpers(_LayerTestCase):

    def test_to_json_produces_valid_json(self):
        filters = [
            FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "Text"),
            FieldFilter(self.layer, "attr_double", FieldFilterType.NUMBER, "Number"),
        ]
        parsed = json.loads(field_filters_to_json(filters))

        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["filter_name"], "Text")
        self.assertEqual(parsed[1]["filter_name"], "Number")

    def test_from_json_roundtrip(self):
        filters = [
            FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "Text"),
            FieldFilter(self.layer, "attr_bool", FieldFilterType.CHECKBOX, "Bool"),
        ]
        restored = field_filters_from_json(field_filters_to_json(filters))

        self.assertEqual(len(restored), 2)
        self.assertEqual(restored[0].field_name, "attr_string")
        self.assertEqual(restored[1].filter_type, FieldFilterType.CHECKBOX)

    def test_from_json_empty(self):
        self.assertEqual(field_filters_from_json("[]"), [])


class TestFieldFilterModel(_LayerTestCase):

    def test_add_filter(self):
        model = FieldFilterModel()
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "My Filter"))

        self.assertEqual(model.rowCount(), 1)

    def test_remove_filter(self):
        model = FieldFilterModel()
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "A"))
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "B"))

        model.remove_filter(0)

        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.filter_names(), ["B"])

    def test_remove_filter_out_of_range(self):
        model = FieldFilterModel()
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "My Filter"))

        model.remove_filter(5)  # no-op, should not raise

        self.assertEqual(model.rowCount(), 1)

    def test_move_filter_down(self):
        model = FieldFilterModel()
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "A"))
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "B"))
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "C"))

        model.move_filter(0, 1)

        self.assertEqual(model.filter_names(), ["B", "A", "C"])

    def test_move_filter_up(self):
        model = FieldFilterModel()
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "A"))
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "B"))

        model.move_filter(1, -1)

        self.assertEqual(model.filter_names(), ["B", "A"])

    def test_move_filter_out_of_range_is_noop(self):
        model = FieldFilterModel()
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "A"))
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "B"))

        model.move_filter(1, 1)  # target index 2 is out of range

        self.assertEqual(model.filter_names(), ["A", "B"])

    def test_filter_names(self):
        model = FieldFilterModel()
        for name in ("First", "Second", "Third"):
            model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, name))

        self.assertEqual(model.filter_names(), ["First", "Second", "Third"])

    def test_json_roundtrip(self):
        model = FieldFilterModel()
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "Text"))
        model.add_filter(FieldFilter(self.layer, "attr_double", FieldFilterType.NUMBER, "Number"))

        model2 = FieldFilterModel()
        model2.load_from_json(model.to_json())

        self.assertEqual(model2.filter_names(), ["Text", "Number"])

    def test_replace_filter(self):
        model = FieldFilterModel()
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "Original"))
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "Other"))

        model.replace_filter(0, FieldFilter(self.layer, "attr_double", FieldFilterType.NUMBER, "Replaced"))

        self.assertEqual(model.rowCount(), 2)
        self.assertEqual(model.filter_names(), ["Replaced", "Other"])

    def test_replace_filter_out_of_range(self):
        model = FieldFilterModel()
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "A"))

        model.replace_filter(5, FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "B"))  # no-op

        self.assertEqual(model.filter_names(), ["A"])

    def test_load_from_json_replaces_existing(self):
        model = FieldFilterModel()
        model.add_filter(FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "Old"))

        new_filters = [FieldFilter(self.layer, "attr_string", FieldFilterType.TEXT, "New")]
        model.load_from_json(field_filters_to_json(new_filters))

        self.assertEqual(model.filter_names(), ["New"])


if __name__ == "__main__":
    nose2.main()
