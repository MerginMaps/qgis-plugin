from collections import defaultdict
import os

from qgis.core import QgsMapLayerType, QgsProject, QgsVectorDataProvider, QgsExpression

from .utils import find_qgis_files, same_dir, QGIS_DB_PROVIDERS, QGIS_NET_PROVIDERS


class MerginProjectValidator(object):
    """Class for checking Mergin project validity and fixing the problems, if possible."""

    NO_PROBLEMS = 0, "No problems found!"  # level, description
    MULTIPLE_PROJS = 0, "Multiple QGIS project files found in the directory"
    PROJ_NOT_LOADED = 0, "The QGIS project is not loaded. Open it to allow validation"
    PROJ_NOT_FOUND = 0, "No QGIS project found in the directory"
    ABSOLUTE_PATHS = 1, "QGIS project saves layers using absolute paths"
    EDITABLE_NON_GPKG = 2, "Editable layer stored in a format other than GeoPackage"
    EXTERNAL_SRC = 3, "Layer stored out of the project directory"
    NOT_FOR_OFFLINE = 5, "Layer might not be available when offline"
    NO_EDITABLE_LAYER = 7, "No editable layer in the project"
    ATTACHMENT_ABSOLUTE_PATH = 8, "Attachment widget uses absolute paths"
    ATTACHMENT_LOCAL_PATH = 9, "Attachment widget uses local path"
    ATTACHMENT_EXPRESSION_PATH = 10, "Attachment widget incorrectly uses expression-based path"

    def __init__(self, mergin_project=None):
        self.mp = mergin_project
        self.layers = None  # {layer_id: map layer}
        self.editable = None  # list of editable layers ids
        self.layers_by_prov = defaultdict(list)  # {provider_name: [layers]}
        self.issues = defaultdict(list)  # {problem type: optional list of problematic data sources, or None}
        self.qgis_files = None
        self.qgis_proj = None
        self.qgis_proj_path = None
        self.qgis_proj_dir = None

    def run_checks(self):
        if self.mp is None:
            # preliminary check for current QGIS project, no Mergin project created yet
            self.qgis_proj_dir = QgsProject.instance().absolutePath()
        else:
            self.qgis_proj_dir = self.mp.dir
        if not self.check_single_proj(self.qgis_proj_dir):
            return self.issues
        if not self.check_proj_loaded():
            return self.issues
        self.get_proj_layers()
        self.check_proj_paths_relative()
        self.check_saved_in_proj_dir()
        self.check_editable_vectors_format()
        self.check_offline()
        self.check_attachment_widget()
        if not self.issues:
            self.issues[self.NO_PROBLEMS] = []
        return self.issues

    def check_single_proj(self, project_dir):
        """Check if there is one and only one QGIS project in the directory."""
        self.qgis_files = find_qgis_files(project_dir)
        if len(self.qgis_files) > 1:
            self.issues[self.MULTIPLE_PROJS] = []
            return False
        elif len(self.qgis_files) == 0:
            # might be deleted after opening in QGIS
            self.issues[self.PROJ_NOT_FOUND] = []
            return False
        return True

    def check_proj_loaded(self):
        """Check if the QGIS project is loaded and validate it eventually. If not, no validation is done."""
        self.qgis_proj_path = self.qgis_files[0]
        loaded_proj_path = QgsProject.instance().absoluteFilePath()
        is_loaded = same_dir(self.qgis_proj_path, loaded_proj_path)
        if not is_loaded:
            self.issues[self.PROJ_NOT_LOADED] = []
        else:
            self.qgis_proj = QgsProject.instance()
        return is_loaded

    def check_proj_paths_relative(self):
        """Check if the QGIS project has relative paths, i.e. not absolute ones."""
        abs_paths, ok = self.qgis_proj.readEntry("Paths", "/Absolute")
        assert ok
        if not abs_paths == "false":
            self.issues[self.ABSOLUTE_PATHS] = []

    def get_proj_layers(self):
        """Get project layers and find those editable."""
        self.layers = self.qgis_proj.mapLayers()
        self.editable = []
        for lid, layer in self.layers.items():
            dp = layer.dataProvider()
            if dp is None:
                continue
            self.layers_by_prov[dp.name()].append(lid)
            if layer.type() == QgsMapLayerType.VectorLayer:
                caps = dp.capabilities()
                can_edit = (
                    True
                    if (caps & QgsVectorDataProvider.AddFeatures or caps & QgsVectorDataProvider.ChangeAttributeValues)
                    else False
                )
                if can_edit:
                    self.editable.append(layer.id())
        if len(self.editable) == 0:
            self.issues[self.NO_EDITABLE_LAYER] = []

    def check_editable_vectors_format(self):
        """Check if editable vector layers are GPKGs."""
        for lid, layer in self.layers.items():
            if lid not in self.editable:
                continue
            dp = layer.dataProvider()
            if not dp.storageType() == "GPKG":
                self.issues[self.EDITABLE_NON_GPKG].append(lid)

    def check_saved_in_proj_dir(self):
        """Check if layers saved in project"s directory."""
        for lid, layer in self.layers.items():
            if lid not in self.layers_by_prov["gdal"] + self.layers_by_prov["ogr"]:
                continue
            pub_src = layer.publicSource()
            if pub_src.startswith("GPKG:"):
                pub_src = pub_src[5:]
                l_path = pub_src[:pub_src.rfind(":")]
            else:
                l_path = layer.publicSource().split("|")[0]
            l_dir = os.path.dirname(l_path)
            if not same_dir(l_dir, self.qgis_proj_dir):
                self.issues[self.EXTERNAL_SRC].append(lid)

    def check_offline(self):
        """Check if there are layers that might not be available when offline"""
        for lid, layer in self.layers.items():
            try:
                dp_name = layer.dataProvider().name()
            except AttributeError:
                # might be vector tiles - no provider name
                continue
            if dp_name in QGIS_NET_PROVIDERS + QGIS_DB_PROVIDERS:
                self.issues[self.NOT_FOR_OFFLINE].append(lid)

    def check_attachment_widget(self):
        """Check if attachment widget uses relative path."""
        for lid, layer in self.layers.items():
            if lid not in self.editable:
                continue

            fields = layer.fields()
            for i in range(fields.count()):
                ws = layer.editorWidgetSetup(i)
                if ws and ws.type() == "ExternalResource":
                    cfg = ws.config()
                    # check for relative paths
                    if cfg["RelativeStorage"] == 0:
                        self.issues[self.ATTACHMENT_ABSOLUTE_PATH].append(lid)
                    if "DefaultRoot" in cfg:
                        # default root should not be set to the local path
                        if os.path.isabs(cfg["DefaultRoot"]):
                            self.issues[self.ATTACHMENT_LOCAL_PATH].append(lid)

                        # expression-based path should be set with the data-defined overrride
                        expr = QgsExpression(cfg["DefaultRoot"])
                        if expr.isValid():
                            self.issues[self.ATTACHMENT_EXPRESSION_PATH].append(lid)
