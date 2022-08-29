from qgis.core import QgsProject

from .utils import copy_datum_shift_grids


def fix_datum_shift_grids(mp):
    qgis_proj_dir = QgsProject.instance().absolutePath()
    if mp is not None:
        qgis_proj_dir = mp.dir

    missed_files = copy_datum_shift_grids(qgis_proj_dir)

    if missed_files:
        return False, f"Following grids were not found in the QGIS folder: {','.join(missed_files)}"

    return True, None
