import os
import shutil

from qgis.core import QgsProject, QgsApplication

from .utils import get_datum_shift_grids


def copy_datum_shift_grids(mp):
    qgis_proj_dir = QgsProject.instance().absolutePath()
    if mp is not None:
        qgis_proj_dir = mp.dir

    proj_dir = os.path.join(qgis_proj_dir, "proj")
    os.makedirs(proj_dir, exist_ok=True)

    missed_files = list()

    grids_dir = os.path.join(QgsApplication.qgisSettingsDirPath(), "proj")
    grids = get_datum_shift_grids()
    for grid in grids.keys():
        if not os.path.exists(os.path.join(qgis_proj_dir, "proj", grid)):
            if not os.path.exists(os.path.join(grids_dir, grid)):
                missed_files.append(grid)
                continue
            shutil.copy(os.path.join(grids_dir, grid), os.path.join(proj_dir, grid))

    if missed_files:
        return False, f"Following grids were not found in the QGIS folder: {','.join(missed_files)}"

    return True, None
