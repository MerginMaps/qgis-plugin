# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited

import os
import shutil

from osgeo import ogr, osr
from qgis.core import QgsVectorLayer

from Mergin.diff import make_local_changes_layer
from Mergin.mergin.merginproject import MerginProject
from Mergin.utils import get_base_file_path, has_schema_change


def make_gpkg(path, names):
    """Create a point layer 'obs' with a 'name' field and one feature per name."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    lyr = ds.CreateLayer("obs", srs, ogr.wkbPoint)
    lyr.CreateField(ogr.FieldDefn("name", ogr.OFTString))
    for i, name in enumerate(names, start=1):
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField("name", name)
        f.SetGeometry(ogr.CreateGeometryFromWkt(f"POINT ({i} {i})"))
        lyr.CreateFeature(f)
    ds = None


def edit_gpkg(path, add_name=None, add_field=None):
    ds = ogr.Open(str(path), update=1)
    lyr = ds.GetLayerByName("obs")
    if add_name:
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField("name", add_name)
        f.SetGeometry(ogr.CreateGeometryFromWkt("POINT (9 9)"))
        lyr.CreateFeature(f)
    if add_field:
        lyr.CreateField(ogr.FieldDefn(add_field, ogr.OFTString))
    ds = None


def make_base_copy(project_dir, rel_path):
    """Copy the file where the client keeps base copies: .mergin/<relative path>."""
    dst = project_dir / ".mergin" / rel_path
    os.makedirs(dst.parent, exist_ok=True)
    shutil.copy(project_dir / rel_path, dst)


def obs_layer(path):
    return QgsVectorLayer(f"{path}|layername=obs", "obs", "ogr")


def test_get_base_file_path(tmp_path):
    mp = MerginProject(str(tmp_path))
    in_subfolder = get_base_file_path(mp, str(tmp_path / "data" / "obs.gpkg"))
    assert in_subfolder == str(tmp_path / ".mergin" / "data" / "obs.gpkg")
    assert get_base_file_path(mp, str(tmp_path.parent / "obs.gpkg")) is None


def test_local_changes_in_subfolder(tmp_path):
    gpkg = tmp_path / "data" / "obs.gpkg"
    make_gpkg(gpkg, ["Concrete", "Wood"])
    make_base_copy(tmp_path, "data/obs.gpkg")
    edit_gpkg(gpkg, add_name="Steel")

    vl, msg = make_local_changes_layer(MerginProject(str(tmp_path)), obs_layer(gpkg))
    assert vl is not None, msg
    assert [f["name"] for f in vl.getFeatures()] == ["Steel"]


def test_local_changes_same_file_name_in_root_and_subfolder(tmp_path):
    make_gpkg(tmp_path / "obs.gpkg", ["Concrete", "Wood"])
    make_gpkg(tmp_path / "data" / "obs.gpkg", ["Brick", "Glass"])
    make_base_copy(tmp_path, "obs.gpkg")
    make_base_copy(tmp_path, "data/obs.gpkg")

    # neither file is edited, so neither has local changes
    vl, msg = make_local_changes_layer(MerginProject(str(tmp_path)), obs_layer(tmp_path / "data" / "obs.gpkg"))
    assert vl is None
    assert msg.startswith("No local changes")


def test_schema_change_in_subfolder(tmp_path):
    gpkg = tmp_path / "data" / "obs.gpkg"
    make_gpkg(gpkg, ["Concrete"])
    make_base_copy(tmp_path, "data/obs.gpkg")
    edit_gpkg(gpkg, add_field="material")

    has_change, _ = has_schema_change(MerginProject(str(tmp_path)), obs_layer(gpkg))
    assert has_change
