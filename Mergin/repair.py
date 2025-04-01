# GPLv3 license
# Copyright Lutra Consulting Limited

from qgis.core import QgsProject

from .utils import project_grids_directory, copy_datum_shift_grids, set_qgis_project_home_ignore


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
