# -*- coding: utf-8 -*-

import os
import base64

from qgis.PyQt.QtCore import QVariant

from qgis.core import (
    QgsVectorLayer,
    QgsField,
    QgsEditorWidgetSetup,
    QgsMarkerSymbol,
    QgsSvgMarkerSymbolLayer,
    QgsSvgMarkerSymbolLayer,
)
from qgis.testing import start_app, unittest

from Mergin.validation import MerginProjectValidator, Warning, SingleLayerWarning

test_data_path = os.path.join(os.path.dirname(__file__), "data")


class test_validations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start_app()

    def tearDown(self):
        pass

    def setUp(self):
        pass

    def test_attachment_widget(self):
        layer = QgsVectorLayer("Point", "test", "memory")
        fields = [QgsField("photo", QVariant.String)]
        layer.dataProvider().addAttributes(fields)
        layer.updateFields()

        validator = MerginProjectValidator()
        validator.layers = {"mem_1": layer}
        validator.editable = ["mem_1"]

        # absolute path
        config = {
            "DocumentViewer": 0,
            "DocumentViewerHeight": 0,
            "DocumentViewerWidth": 0,
            "FileWidget": True,
            "FileWidgetButton": True,
            "FileWidgetFilter": "",
            "PropertyCollection": {"name": None, "properties": {}, "type": "collection"},
            "RelativeStorage": 0,
            "StorageAuthConfigId": None,
            "StorageMode": 0,
            "StorageType": None,
        }
        widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
        layer.setEditorWidgetSetup(0, widget_setup)
        validator.check_attachment_widget()
        self.assertTrue(len(validator.issues) == 1)
        issue = validator.issues[0]
        self.assertTrue(isinstance(issue, SingleLayerWarning))
        self.assertEqual(issue.layer_id, "mem_1")
        self.assertEqual(issue.warning, Warning.ATTACHMENT_ABSOLUTE_PATH)
        validator.issues = []

        # local path
        config["RelativeStorage"] = 1
        config["DefaultRoot"] = "/tmp/photos"
        widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
        layer.setEditorWidgetSetup(0, widget_setup)
        validator.check_attachment_widget()
        self.assertTrue(len(validator.issues) == 1)
        issue = validator.issues[0]
        self.assertTrue(isinstance(issue, SingleLayerWarning))
        self.assertEqual(issue.layer_id, "mem_1")
        self.assertEqual(issue.warning, Warning.ATTACHMENT_LOCAL_PATH)
        validator.issues = []

        # default path not expression
        config["DefaultRoot"] = "@project_home + '/Photos'"
        widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
        layer.setEditorWidgetSetup(0, widget_setup)
        validator.check_attachment_widget()
        self.assertTrue(len(validator.issues) == 1)
        issue = validator.issues[0]
        self.assertTrue(isinstance(issue, SingleLayerWarning))
        self.assertEqual(issue.layer_id, "mem_1")
        self.assertEqual(issue.warning, Warning.ATTACHMENT_EXPRESSION_PATH)
        validator.issues = []

        # uses link
        config["DefaultRoot"] = ""
        config["UseLink"] = True
        widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
        layer.setEditorWidgetSetup(0, widget_setup)
        validator.check_attachment_widget()
        self.assertTrue(len(validator.issues) == 1)
        issue = validator.issues[0]
        self.assertTrue(isinstance(issue, SingleLayerWarning))
        self.assertEqual(issue.layer_id, "mem_1")
        self.assertEqual(issue.warning, Warning.ATTACHMENT_HYPERLINK)
        validator.issues = []

        # valid expression
        del config["UseLink"]
        config["PropertyCollection"] = {
            "name": "0",
            "properties": {"propertyRootPath": {"active": True, "expression": "'/Photos'", "type": 3}},
            "type": "collection",
        }
        widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
        layer.setEditorWidgetSetup(0, widget_setup)
        validator.check_attachment_widget()
        self.assertTrue(len(validator.issues) == 1)
        issue = validator.issues[0]
        self.assertTrue(isinstance(issue, SingleLayerWarning))
        self.assertEqual(issue.layer_id, "mem_1")
        self.assertEqual(issue.warning, Warning.ATTACHMENT_WRONG_EXPRESSION)
        validator.issues = []

    def test_embedded_svg(self):
        layer = QgsVectorLayer("Point", "test", "memory")
        symbol = QgsMarkerSymbol()
        symbol_layer = QgsSvgMarkerSymbolLayer(os.path.join(test_data_path, "transport_aerodrome.svg"))
        symbol.changeSymbolLayer(0, symbol_layer)
        layer.renderer().setSymbol(symbol)

        validator = MerginProjectValidator()
        validator.layers = {"mem_1": layer}
        validator.editable = ["mem_1"]

        validator.check_svgs_embedded()
        self.assertTrue(len(validator.issues) == 1)
        issue = validator.issues[0]
        self.assertTrue(isinstance(issue, SingleLayerWarning))
        self.assertEqual(issue.layer_id, "mem_1")
        self.assertEqual(issue.warning, Warning.SVG_NOT_EMBEDDED)
        validator.issues = []

        data = None
        with open(os.path.join(test_data_path, "transport_aerodrome.svg"), "r") as f:
            data = f.read()

        svg = f"base64:{base64.b64encode(data.encode('utf-8')).decode('utf-8')}"
        print("SVG", svg)
        symbol = QgsMarkerSymbol()
        symbol_layer = QgsSvgMarkerSymbolLayer(svg)
        symbol.changeSymbolLayer(0, symbol_layer)
        layer.renderer().setSymbol(symbol)

        validator.layers = {"mem_1": layer}
        validator.editable = ["mem_1"]
        validator.check_svgs_embedded()
        self.assertTrue(len(validator.issues) == 0)


if __name__ == "__main__":
    nose2.main()
