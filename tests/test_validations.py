# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited


import base64
from pathlib import Path

from qgis.core import (
    QgsDataSourceUri,
    QgsEditorWidgetSetup,
    QgsField,
    QgsMarkerSymbol,
    QgsProject,
    QgsRasterLayer,
    QgsSingleSymbolRenderer,
    QgsSvgMarkerSymbolLayer,
    QgsVectorLayer,
    QgsVectorTileLayer,
)
from qgis.gui import QgsFileWidget
from qgis.PyQt.QtCore import QVariant

from Mergin.utils import TILES_URL
from Mergin.validation import MerginProjectValidator, SingleLayerWarning, Warning


def test_attachment_widget(mem_layer: QgsVectorLayer, project_dir: Path):
    photo_field = [QgsField("photo", QVariant.String)]
    mem_layer.dataProvider().addAttributes(photo_field)
    mem_layer.updateFields()
    fields = mem_layer.fields()
    photo_field_idx = fields.indexFromName("photo")

    validator = MerginProjectValidator()
    validator.layers = {mem_layer.id(): mem_layer}
    validator.editable = [mem_layer.id()]
    validator.qgis_proj_dir = project_dir

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
            "properties": None,
            "type": "collection",
        },
        "RelativeStorage": QgsFileWidget.RelativeStorage.Absolute,
        "StorageAuthConfigId": None,
        "StorageMode": 0,
        "StorageType": None,
    }
    widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
    mem_layer.setEditorWidgetSetup(photo_field_idx, widget_setup)
    validator.check_attachment_widget()
    assert len(validator.issues) == 1
    issue = validator.issues[0]
    assert isinstance(issue, SingleLayerWarning)
    assert issue.layer_id == mem_layer.id()
    assert issue.warning == Warning.ATTACHMENT_ABSOLUTE_PATH
    validator.issues = []

    # local path
    config["RelativeStorage"] = QgsFileWidget.RelativeStorage.RelativeProject
    config["DefaultRoot"] = str(Path(project_dir) / "photos")
    widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
    mem_layer.setEditorWidgetSetup(photo_field_idx, widget_setup)
    validator.check_attachment_widget()
    assert len(validator.issues) == 1
    issue = validator.issues[0]
    assert isinstance(issue, SingleLayerWarning)
    assert issue.layer_id == mem_layer.id()
    assert issue.warning == Warning.ATTACHMENT_LOCAL_PATH
    validator.issues = []

    # default path expression - wrong setup
    config["DefaultRoot"] = "@project_home + '/Photos'"
    widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
    mem_layer.setEditorWidgetSetup(photo_field_idx, widget_setup)
    validator.check_attachment_widget()
    assert len(validator.issues) == 1
    issue = validator.issues[0]
    assert isinstance(issue, SingleLayerWarning)
    assert issue.layer_id == mem_layer.id()
    assert issue.warning == Warning.ATTACHMENT_EXPRESSION_PATH
    validator.issues = []

    # right setup, wrong expression
    del config["DefaultRoot"]
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
    mem_layer.setEditorWidgetSetup(photo_field_idx, widget_setup)
    validator.check_attachment_widget()
    assert len(validator.issues) == 1
    issue = validator.issues[0]
    assert isinstance(issue, SingleLayerWarning)
    assert issue.layer_id == mem_layer.id()
    assert issue.warning == Warning.ATTACHMENT_WRONG_EXPRESSION
    validator.issues = []

    # right setup, valid expression
    config["PropertyCollection"]["properties"]["propertyRootPath"]["expression"] = "@project_folder + '/photos'"
    config["DefaultRoot"] = str(Path(project_dir) / "photos")  # default root should be override
    widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
    mem_layer.setEditorWidgetSetup(photo_field_idx, widget_setup)
    validator.check_attachment_widget()
    assert len(validator.issues) == 0

    # right setup, field-based override (Type 2)
    config["PropertyCollection"]["properties"]["propertyRootPath"] = {
        "active": True,
        "field": "photo",
        "expression": "",
        "type": 2,
    }
    widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
    mem_layer.setEditorWidgetSetup(photo_field_idx, widget_setup)
    validator.check_attachment_widget()
    assert len(validator.issues) == 0

    # right setup, expression-based override with quoted field name (Type 3)
    config["PropertyCollection"]["properties"]["propertyRootPath"] = {
        "active": True,
        "expression": '"photo"',
        "type": 3,
    }
    widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
    mem_layer.setEditorWidgetSetup(photo_field_idx, widget_setup)
    validator.check_attachment_widget()
    assert len(validator.issues) == 0

    # absolute path bypass when storageUrl is active (e.g. Google Drive URLs)
    config["RelativeStorage"] = QgsFileWidget.RelativeStorage.Absolute
    config["PropertyCollection"]["properties"] = {
        "storageUrl": {
            "active": True,
            "field": "photo",
            "type": 2,
        }
    }
    # clear DefaultRoot doesn't trigger the warning
    config.pop("DefaultRoot", None)
    widget_setup = QgsEditorWidgetSetup("ExternalResource", config)
    mem_layer.setEditorWidgetSetup(photo_field_idx, widget_setup)
    validator.check_attachment_widget()
    assert len(validator.issues) == 0


def test_embedded_svg(mem_layer: QgsVectorLayer, project_dir: Path, test_data_path: Path):
    symbol = QgsMarkerSymbol()
    symbol_layer = QgsSvgMarkerSymbolLayer(str(test_data_path / "transport_aerodrome.svg"))
    symbol.changeSymbolLayer(0, symbol_layer)
    renderer = mem_layer.renderer()
    assert isinstance(renderer, QgsSingleSymbolRenderer)
    renderer.setSymbol(symbol)

    validator = MerginProjectValidator()
    validator.layers = {mem_layer.id(): mem_layer}
    validator.editable = [mem_layer.id()]
    validator.qgis_proj_dir = project_dir

    validator.check_svgs_embedded()
    assert len(validator.issues) == 1
    issue = validator.issues[0]
    assert isinstance(issue, SingleLayerWarning)
    assert issue.layer_id == mem_layer.id()
    assert issue.warning == Warning.SVG_NOT_EMBEDDED
    validator.issues = []

    with open(test_data_path / "transport_aerodrome.svg", "r") as f:
        data = f.read()

    svg = f"base64:{base64.b64encode(data.encode('utf-8')).decode('utf-8')}"
    symbol = QgsMarkerSymbol()
    symbol_layer = QgsSvgMarkerSymbolLayer(svg)
    symbol.changeSymbolLayer(0, symbol_layer)
    renderer = mem_layer.renderer()
    assert isinstance(renderer, QgsSingleSymbolRenderer)
    renderer.setSymbol(symbol)

    validator.layers = {mem_layer.id(): mem_layer}
    validator.editable = [mem_layer.id()]
    validator.check_svgs_embedded()
    assert len(validator.issues) == 0


def test_local_mbtiles(raster_tiles_path: Path, vector_tiles_path: Path):
    rt_layer = QgsRasterLayer(f"url=file://{raster_tiles_path.as_posix()}&type=mbtiles", "test_raster", "wms")
    assert rt_layer.isValid()

    vt_layer = QgsVectorTileLayer(f"url={vector_tiles_path.as_posix()}&type=mbtiles", "test_vector")
    assert vt_layer.isValid()

    validator = MerginProjectValidator()
    validator.layers = {"test_raster": rt_layer, "test_vector": vt_layer}

    validator.check_offline()
    assert len(validator.issues) == 0
    validator.issues = []

    ds_uri = QgsDataSourceUri()
    ds_uri.setParam("type", "xyz")
    ds_uri.setParam("url", f"{TILES_URL}/data/default/{{z}}/{{x}}/{{y}}.pbf")
    ds_uri.setParam("zmin", "0")
    ds_uri.setParam("zmax", "14")
    ds_uri.setParam("styleUrl", f"{TILES_URL}/styles/default.json")
    vt_layer_online = QgsVectorTileLayer(bytes(ds_uri.encodedUri()).decode(), "test_vector_online")
    assert vt_layer_online.isValid()

    validator.layers["test_vector_online"] = vt_layer_online
    validator.check_offline()
    assert len(validator.issues) == 1
