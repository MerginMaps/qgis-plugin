# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited


import os
import base64
import shutil
import tempfile

from qgis.PyQt.QtCore import QVariant

from qgis.core import (
    QgsProject,
    QgsField,
    QgsEditorWidgetSetup,
    QgsMarkerSymbol,
    QgsSvgMarkerSymbolLayer,
    QgsRasterLayer,
    QgsVectorTileLayer,
    QgsDataSourceUri,
)
from qgis.testing import start_app, unittest

from Mergin.test.test_help import create_mem_layer
from Mergin.validation import MerginProjectValidator, Warning, SingleLayerWarning
from Mergin.utils import TILES_URL


test_data_path = os.path.join(os.path.dirname(__file__), "data")


class test_validations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start_app()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.mem_layer = create_mem_layer()
        temp_proj = QgsProject.instance()
        temp_proj.addMapLayer(self.mem_layer)
        temp_proj.setFileName(f"{self.temp_dir}/test_project.qgz")

    def test_attachment_widget(self):
        photo_field = [QgsField("photo", QVariant.String)]
        self.mem_layer.dataProvider().addAttributes(photo_field)
        self.mem_layer.updateFields()
        fields = self.mem_layer.fields()
        photo_field_idx = fields.indexFromName("photo")

        validator = MerginProjectValidator()
        validator.layers = {self.mem_layer.id(): self.mem_layer}
        validator.editable = [self.mem_layer.id()]
        validator.qgis_proj_dir = self.temp_dir

        # absolute path
        config = {
            "DocumentViewer": 0,
            "DocumentViewerHeight": 0,
            "DocumentViewerWidth": 0,
            "FileWidget": True,
            "FileWidgetButton": True,
            "FileWidgetFilter": "",
            "PropertyCollection": {
                "name": None,
                "properties": {},
                "type": "collection",
            },
            "RelativeStorage": 0,
            "StorageAuthConfigId": None,
            "StorageMode": 0,
            "StorageType": None,
        }
        widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
        self.mem_layer.setEditorWidgetSetup(photo_field_idx, widget_setup)
        validator.check_attachment_widget()
        self.assertTrue(len(validator.issues) == 1)
        issue = validator.issues[0]
        self.assertTrue(isinstance(issue, SingleLayerWarning))
        self.assertEqual(issue.layer_id, self.mem_layer.id())
        self.assertEqual(issue.warning, Warning.ATTACHMENT_ABSOLUTE_PATH)
        validator.issues = []

        # local path
        config["RelativeStorage"] = 2
        config["DefaultRoot"] = "/tmp/photos"
        widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
        self.mem_layer.setEditorWidgetSetup(photo_field_idx, widget_setup)
        validator.check_attachment_widget()
        self.assertTrue(len(validator.issues) == 1)
        issue = validator.issues[0]
        self.assertTrue(isinstance(issue, SingleLayerWarning))
        self.assertEqual(issue.layer_id, self.mem_layer.id())
        self.assertEqual(issue.warning, Warning.ATTACHMENT_LOCAL_PATH)
        validator.issues = []

        # default path expression
        config["DefaultRoot"] = "@project_home + '/Photos'"
        widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
        self.mem_layer.setEditorWidgetSetup(photo_field_idx, widget_setup)
        validator.check_attachment_widget()
        self.assertTrue(len(validator.issues) == 0)

        # relative to project path
        config["RelativeStorage"] = 1
        config.pop("DefaultRoot", None)
        widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
        self.mem_layer.setEditorWidgetSetup(photo_field_idx, widget_setup)
        validator.check_attachment_widget()
        self.assertTrue(len(validator.issues) == 0)

        # uses link
        config["RelativeStorage"] = 2
        config["UseLink"] = True
        widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
        self.mem_layer.setEditorWidgetSetup(photo_field_idx, widget_setup)
        validator.check_attachment_widget()
        self.assertTrue(len(validator.issues) == 1)
        issue = validator.issues[0]
        self.assertTrue(isinstance(issue, SingleLayerWarning))
        self.assertEqual(issue.layer_id, self.mem_layer.id())
        self.assertEqual(issue.warning, Warning.ATTACHMENT_HYPERLINK)
        validator.issues = []

        # valid expression
        del config["UseLink"]
        config["PropertyCollection"] = {
            "name": "0",
            "properties": {
                "propertyRootPath": {
                    "active": True,
                    "expression": "'/Photos'",
                    "type": 3,
                }
            },
            "type": "collection",
        }
        widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
        self.mem_layer.setEditorWidgetSetup(photo_field_idx, widget_setup)
        validator.check_attachment_widget()
        self.assertTrue(len(validator.issues) == 1)
        issue = validator.issues[0]
        self.assertTrue(isinstance(issue, SingleLayerWarning))
        self.assertEqual(issue.layer_id, self.mem_layer.id())
        self.assertEqual(issue.warning, Warning.ATTACHMENT_WRONG_EXPRESSION)
        validator.issues = []

    def test_embedded_svg(self):
        symbol = QgsMarkerSymbol()
        symbol_layer = QgsSvgMarkerSymbolLayer(os.path.join(test_data_path, "transport_aerodrome.svg"))
        symbol.changeSymbolLayer(0, symbol_layer)
        self.mem_layer.renderer().setSymbol(symbol)

        validator = MerginProjectValidator()
        validator.layers = {self.mem_layer.id(): self.mem_layer}
        validator.editable = [self.mem_layer.id()]
        validator.qgis_proj_dir = self.temp_dir

        validator.check_svgs_embedded()
        self.assertTrue(len(validator.issues) == 1)
        issue = validator.issues[0]
        self.assertTrue(isinstance(issue, SingleLayerWarning))
        self.assertEqual(issue.layer_id, self.mem_layer.id())
        self.assertEqual(issue.warning, Warning.SVG_NOT_EMBEDDED)
        validator.issues = []

        data = None
        with open(os.path.join(test_data_path, "transport_aerodrome.svg"), "r") as f:
            data = f.read()

        svg = f"base64:{base64.b64encode(data.encode('utf-8')).decode('utf-8')}"
        symbol = QgsMarkerSymbol()
        symbol_layer = QgsSvgMarkerSymbolLayer(svg)
        symbol.changeSymbolLayer(0, symbol_layer)
        self.mem_layer.renderer().setSymbol(symbol)

        validator.layers = {self.mem_layer.id(): self.mem_layer}
        validator.editable = [self.mem_layer.id()]
        validator.check_svgs_embedded()
        self.assertTrue(len(validator.issues) == 0)

    def test_local_mbtiles(self):
        raster_tiles_path = os.path.join(test_data_path, "raster-tiles.mbtiles")
        rt_layer = QgsRasterLayer(f"url=file://{raster_tiles_path}&type=mbtiles", "test_raster", "wms")
        self.assertTrue(rt_layer.isValid())

        vector_tiles_path = os.path.join(test_data_path, "vector-tiles.mbtiles")
        vt_layer = QgsVectorTileLayer(f"url={vector_tiles_path}&type=mbtiles", "test_vector")
        self.assertTrue(vt_layer.isValid())

        validator = MerginProjectValidator()
        validator.layers = {"test_raster": rt_layer, "test_vector": vt_layer}

        validator.check_offline()
        self.assertEqual(len(validator.issues), 0)
        validator.issues = []

        ds_uri = QgsDataSourceUri()
        ds_uri.setParam("type", "xyz")
        ds_uri.setParam("url", f"{TILES_URL}/data/default/{{z}}/{{x}}/{{y}}.pbf")
        ds_uri.setParam("zmin", "0")
        ds_uri.setParam("zmax", "14")
        ds_uri.setParam("styleUrl", f"{TILES_URL}/styles/default.json")
        vt_layer_online = QgsVectorTileLayer(bytes(ds_uri.encodedUri()).decode(), "test_vector_online")
        self.assertTrue(vt_layer_online.isValid())

        validator.layers["test_vector_online"] = vt_layer_online
        validator.check_offline()
        self.assertEqual(len(validator.issues), 1)


if __name__ == "__main__":
    nose2.main()
