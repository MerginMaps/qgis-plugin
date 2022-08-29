from qgis.core import QgsProject

from .utils import copy_datum_shift_grids


def fix_datum_shift_grids(mp):
    """
    Copies datum shift grids to the MerginMaps project directory.
    Returns None on success and error message if some grids were not
    copied.
    """
    qgis_proj_dir = mp.dir
    missed_files = copy_datum_shift_grids(qgis_proj_dir)
    if missed_files:
        return f"Following grids were not found in the QGIS folder: {','.join(missed_files)}"

    return None
