# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited

from pathlib import Path
from unittest.mock import MagicMock

from osgeo import ogr
from qgis.core import (
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsProject,
    QgsRendererCategory,
    QgsSymbol,
    QgsVectorLayer,
)

from Mergin.projects_manager import MerginProjectsManager


def create_gpkg(path: Path, geom_type: int):
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    ds.CreateLayer("data", geom_type=geom_type).CreateField(ogr.FieldDefn("kind", ogr.OFTString))


def add_feature(path: Path, kind: str):
    """Write a feature through a connection QGIS doesn't know about, as a pull does."""
    ds = ogr.Open(str(path), update=1)
    layer = ds.GetLayer(0)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetField("kind", kind)
    layer.CreateFeature(feature)


def legend_counts(layer: QgsVectorLayer) -> dict:
    """Count features per legend item, as the layer tree does when it shows feature counts."""
    counter = layer.countSymbolFeatures()
    if counter:  # None while QGIS considers its earlier counts current
        counter.waitForFinished()
        QgsApplication.processEvents()
    return {item.label(): layer.featureCount(item.ruleKey()) for item in layer.renderer().legendSymbolItems()}


def test_reload_project_layers(tmp_path: Path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    paths = [project_dir / "points.gpkg", project_dir / "notes.gpkg", tmp_path / "outside.gpkg"]
    for path, geom_type in zip(paths, [ogr.wkbPoint, ogr.wkbNone, ogr.wkbPoint]):
        create_gpkg(path, geom_type)
        add_feature(path, "Concrete")
    points, notes, outside = [QgsVectorLayer(f"{path}|layername=data", path.stem, "ogr") for path in paths]
    for layer in (points, outside):
        symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        categories = [QgsRendererCategory(kind, symbol.clone(), kind) for kind in ("Concrete", "Steel")]
        layer.setRenderer(QgsCategorizedSymbolRenderer("kind", categories))
    QgsProject.instance().addMapLayers([points, notes, outside])
    try:
        assert legend_counts(points) == {"Concrete": 1, "Steel": 0}
        for path in paths:
            add_feature(path, "Steel")
        assert points.featureCount() == 1  # QGIS still has the count it cached

        manager = MerginProjectsManager(MagicMock())
        manager.iface = MagicMock()
        manager.reload_project_layers(str(project_dir))

        assert points.featureCount() == notes.featureCount() == 2
        assert legend_counts(points) == {"Concrete": 1, "Steel": 1}
        manager.iface.layerTreeView().refreshLayerSymbology.assert_called_once_with(notes.id())
        assert outside.featureCount() == 1  # layers from other folders are left alone
    finally:
        QgsProject.instance().removeMapLayers([points.id(), notes.id(), outside.id()])
