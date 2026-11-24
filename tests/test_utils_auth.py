# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited

from pathlib import Path

import pytest
from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

from Mergin.utils_auth import AuthSync

# Port 9 (discard) refuses connections, so providers fail fast without network access.
WFS_URI = "authcfg=wfsat01 typename='ns:layer' url='http://127.0.0.1:9/wfs' version='auto'"
WMS_URI = "authcfg=wmsat01&crs=EPSG:4326&format=image/png&layers=layer&styles=&url=http://127.0.0.1:9/wms"
OAPIF_URI = "authcfg=oapifa1 typename='layer' url='http://127.0.0.1:9/ogcapi'"
NO_AUTH_WFS_URI = "typename='ns:layer' url='http://127.0.0.1:9/wfs' version='auto'"


@pytest.fixture
def auth_project(mergin_project_dir: Path):
    """Current QGIS project in a Mergin Maps project folder, cleaned up afterwards."""
    proj = QgsProject.instance()
    proj.setFileName(str(mergin_project_dir / "survey.qgz"))
    yield proj
    proj.clear()


def add_layer(proj: QgsProject, layer) -> None:
    # Layers with an unreachable source are invalid but they keep their source and must still be detected.
    proj.addMapLayer(layer)
    assert layer.id() in proj.mapLayers()


def test_get_layers_auth_ids_wfs(auth_project: QgsProject):
    add_layer(auth_project, QgsVectorLayer(WFS_URI, "wfs", "WFS"))
    assert AuthSync().get_layers_auth_ids() == ["wfsat01"]


def test_get_layers_auth_ids_mixed_providers(auth_project: QgsProject):
    add_layer(auth_project, QgsVectorLayer(WFS_URI, "wfs", "WFS"))
    add_layer(auth_project, QgsRasterLayer(WMS_URI, "wms", "wms"))
    add_layer(auth_project, QgsVectorLayer(OAPIF_URI, "oapif", "OAPIF"))
    add_layer(auth_project, QgsVectorLayer(NO_AUTH_WFS_URI, "wfs no auth", "WFS"))
    add_layer(auth_project, QgsVectorLayer("Point", "memory", "memory"))
    assert sorted(AuthSync().get_layers_auth_ids()) == ["oapifa1", "wfsat01", "wmsat01"]
