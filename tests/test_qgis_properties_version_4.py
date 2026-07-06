# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited

from pathlib import Path

from Mergin.qgis_properties_version_4 import is_qgis_version_4, read_mergin_properties


def test_is_qgis_version_4(qgis_project_4_path: Path):
    assert is_qgis_version_4(str(qgis_project_4_path))


def test_read_mergin_properties(qgis_project_4_path: Path):

    mergin_properties = read_mergin_properties(str(qgis_project_4_path))

    assert isinstance(mergin_properties, dict)
    assert len(mergin_properties) > 0
