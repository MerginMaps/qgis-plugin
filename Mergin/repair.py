# GPLv3 license
# Copyright Lutra Consulting Limited

from qgis.core import QgsProject, QgsEditorWidgetSetup

from .utils import (
    project_grids_directory,
    copy_datum_shift_grids,
    set_qgis_project_home_ignore,
)


def fix_datum_shift_grids(mp):
    """
    Copies datum shift grids to the MerginMaps project directory.
    Returns None on success and error message if some grids were not
    copied.
    """
    if mp is None:
        return "Invalid Mergin Maps project"

    grids_directory = project_grids_directory(mp)
    if grids_directory is None:
        return "Failed to get destination path for grids"

    missed_files = copy_datum_shift_grids(grids_directory)
    if missed_files:
        return f"Following grids were not found in the QGIS folder: {','.join(missed_files)}"

    return None


def fix_project_home_path():
    """Remove home path settings from the project."""
    cur_project = QgsProject.instance()
    set_qgis_project_home_ignore(cur_project)
    return None


def activate_expression(layer_id, field_name):
    """Attachment widget uses default path without data-defined override. Move it to the right place."""
    layer = QgsProject.instance().mapLayer(layer_id)
    field_idx = layer.fields().indexFromName(field_name)
    ws = layer.editorWidgetSetup(field_idx)
    cfg = ws.config().copy()
    # blank (MM) projects lack some keys
    pc = cfg.setdefault("PropertyCollection", {})
    props = pc.setdefault("properties", {})
    prp = props.setdefault("propertyRootPath", {})
    # copy the path to the expression and activate data-defined override
    default_root = cfg.pop("DefaultRoot", None)
    if default_root is not None:
        prp["expression"] = default_root
        prp["active"] = True
        prp["type"] = 3
    new_ws = QgsEditorWidgetSetup(ws.type(), cfg)
    layer.setEditorWidgetSetup(field_idx, new_ws)
