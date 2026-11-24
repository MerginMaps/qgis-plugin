# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

from Mergin import utils_auth
from Mergin.utils_auth import AuthSync

# Port 9 (discard) refuses connections, so providers fail fast without network access.
WFS_URI = "authcfg=wfsat01 typename='ns:layer' url='http://127.0.0.1:9/wfs' version='auto'"
WMS_URI = "authcfg=wmsat01&crs=EPSG:4326&format=image/png&layers=layer&styles=&url=http://127.0.0.1:9/wms"
NO_AUTH_WFS_URI = "typename='ns:layer' url='http://127.0.0.1:9/wfs' version='auto'"


@pytest.fixture
def auth_project(tmp_path: Path, monkeypatch):
    """Current QGIS project saved in a temporary folder, cleaned up afterwards."""
    # get_layers_auth_ids does not use the Mergin Maps project metadata.
    monkeypatch.setattr(utils_auth, "MerginProject", MagicMock())
    proj = QgsProject.instance()
    proj.setFileName(str(tmp_path / "survey.qgz"))
    yield proj
    proj.clear()


def add_layer(proj: QgsProject, layer) -> None:
    # Layers with an unreachable source are invalid, as on a machine without the auth config,
    # but they keep their source and must still be detected.
    proj.addMapLayer(layer)
    assert layer.id() in proj.mapLayers()


def test_get_layers_auth_ids_wfs(auth_project: QgsProject):
    add_layer(auth_project, QgsVectorLayer(WFS_URI, "wfs", "WFS"))
    assert AuthSync().get_layers_auth_ids() == ["wfsat01"]


def test_get_layers_auth_ids_mixed_providers(auth_project: QgsProject):
    add_layer(auth_project, QgsVectorLayer(WFS_URI, "wfs", "WFS"))
    add_layer(auth_project, QgsRasterLayer(WMS_URI, "wms", "wms"))
    add_layer(auth_project, QgsVectorLayer(NO_AUTH_WFS_URI, "wfs no auth", "WFS"))
    add_layer(auth_project, QgsVectorLayer("Point", "memory", "memory"))
    assert sorted(AuthSync().get_layers_auth_ids()) == ["wfsat01", "wmsat01"]
