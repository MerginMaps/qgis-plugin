# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited


import os
import tempfile
import urllib.request

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsVectorLayer,
    QgsFields,
    QgsField,
    QgsVectorFileWriter,
    QgsWkbTypes,
    QgsCoordinateTransformContext,
    QgsCoordinateReferenceSystem,
    QgsProject,
)
from qgis.testing import start_app, unittest
from Mergin.help import MerginHelp

test_data_path = os.path.join(os.path.dirname(__file__), "data")


class test_help(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start_app()

    def test_help_urls(self):
        mh = MerginHelp()

        req = urllib.request.Request(mh.howto_attachment_widget(), method="HEAD")
        resp = urllib.request.urlopen(req)
        self.assertEqual(resp.status, 200)

        req = urllib.request.Request(mh.howto_background_maps(), method="HEAD")
        resp = urllib.request.urlopen(req)
        self.assertEqual(resp.status, 200)


def create_temp_layer(location, name="test_layer", driver="GPKG") -> QgsVectorLayer:
    """
    Create a temporary file-based vector layer (default: GeoPackage).
    Returns a QgsVectorLayer that you can use in tests.
    """
    path = os.path.join(location, f"{name}.gpkg" if driver == "GPKG" else f"{name}.shp")
    # temp_project = QgsProject()

    fields = QgsFields()
    fields.append(QgsField("id", QVariant.Int))
    fields.append(QgsField("name", QVariant.String))

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver
    options.layerName = name

    writer = QgsVectorFileWriter.create(
        path,
        fields,
        QgsWkbTypes.Point,
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsCoordinateTransformContext(),
        options,
    )
    del writer

    layer = QgsVectorLayer(path, name, "ogr")
    if not layer.isValid():
        raise RuntimeError(f"Failed to create test layer at {path}")
    # temp_project.addMapLayer(layer)

    return layer


if __name__ == "__main__":
    nose2.main()
