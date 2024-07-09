import os
import shutil

profile = "default"

this_dir = os.path.dirname(os.path.realpath(__file__))
home_dir = os.path.expanduser("~")
dest_dir_plug = os.path.join(home_dir, "AppData", "Roaming", "QGIS", "QGIS3", "profiles", profile, "python", "plugins", "Mergin")
print(dest_dir_plug)
src_dir_plug = os.path.join(os.path.dirname(this_dir), "Mergin")
try:
    shutil.rmtree(dest_dir_plug)
except OSError:
    print("Could not remove Mergin")
shutil.copytree(src_dir_plug, dest_dir_plug)
