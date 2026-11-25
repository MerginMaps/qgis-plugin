# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from qgis.core import QgsExpressionContextUtils, QgsProject

from Mergin.projects_manager import MerginProjectsManager
from Mergin.utils import remove_project_variables, write_project_version_variable


@pytest.mark.parametrize(
    "synced_project_is_open, expected_version",
    [
        pytest.param(True, 3),
        pytest.param(False, 1),
    ],
)
def test_version_variable_refreshed_only_for_open_project(
    mergin_project_dir: Path, monkeypatch: pytest.MonkeyPatch, synced_project_is_open: bool, expected_version: int
):
    """Sync from the Browser panel can run on a project that isn't open, which must not change the open one."""
    # the open project shows v1, the synced project's metadata is at v3 (see the fixture)
    write_project_version_variable("v1")
    # no .qgz is open in the test, so tell the manager which project folder is open
    open_project_dir = mergin_project_dir if synced_project_is_open else mergin_project_dir / "other"
    monkeypatch.setattr("Mergin.projects_manager.mergin_project_local_path", lambda: str(open_project_dir))

    MerginProjectsManager(MagicMock()).refresh_project_version_variable(str(mergin_project_dir))

    project_scope = QgsExpressionContextUtils.projectScope(QgsProject.instance())
    assert project_scope.variable("mm_project_version") == expected_version
    remove_project_variables()
