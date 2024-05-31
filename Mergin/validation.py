import os
import re
from enum import Enum
from collections import defaultdict

from qgis.core import (
    QgsMapLayerType,
    QgsProject,
    QgsVectorDataProvider,
    QgsExpression,
    QgsRenderContext,
)

from .help import MerginHelp
from .utils import (
    find_qgis_files,
    same_dir,
    has_schema_change,
    get_primary_keys,
    get_datum_shift_grids,
    project_grids_directory,
    QGIS_DB_PROVIDERS,
    QGIS_NET_PROVIDERS,
)

INVALID_CHARS = re.compile('[\\\/\(\)\[\]\{\}"\n\r]')
PROJECT_VARS = re.compile("\@project_home|\@project_path|\@project_folder")


class Warning(Enum):
    PROJ_NOT_LOADED = 1
    PROJ_NOT_FOUND = 2
    MULTIPLE_PROJS = 3
    ABSOLUTE_PATHS = 4
    EDITABLE_NON_GPKG = 5
    EXTERNAL_SRC = 6
    NOT_FOR_OFFLINE = 7
    NO_EDITABLE_LAYERS = 8
    ATTACHMENT_ABSOLUTE_PATH = 9
    ATTACHMENT_LOCAL_PATH = 10
    ATTACHMENT_EXPRESSION_PATH = 11
    ATTACHMENT_HYPERLINK = 12
    DATABASE_SCHEMA_CHANGE = 13
    KEY_FIELD_NOT_UNIQUE = 14
    FIELD_IS_PRIMARY_KEY = 15
    VALUE_RELATION_LAYER_MISSED = 16
    INCORRECT_FIELD_NAME = 17
    BROKEN_VALUE_RELATION_CONFIG = 18
    ATTACHMENT_WRONG_EXPRESSION = 19
    QGIS_SNAPPING_NOT_ENABLED = 20
    MERGIN_SNAPPING_NOT_ENABLED = 21
    MISSING_DATUM_SHIFT_GRID = 22
    SVG_NOT_EMBEDDED = 23
    EDITOR_PROJECT_FILE_CHANGE = 24
    EDITOR_NON_DIFFABLE_CHANGE = 25

class MultipleLayersWarning:
    """Class for warning which is associated with multiple layers.

    Some warnings, e.g. "layer not suitable for offline use" should be
    displayed only once in the validation results and list all matching
    layers.
    """

    def __init__(self, warning_id, url=""):
        self.id = warning_id
        self.items = list()
        self.url = url


class SingleLayerWarning:
    """Class for warning which is associated with single layer."""

    def __init__(self, layer_id, warning, url=""):
        self.layer_id = layer_id
        self.warning = warning
        self.url = url


class MerginProjectValidator(object):
    """Class for checking Mergin project validity and fixing the problems, if possible."""

    def __init__(self, mergin_project=None, changes=None, project_permission=None):
        self.mp = mergin_project
        self.layers = None  # {layer_id: map layer}
        self.editable = None  # list of editable layers ids
        self.layers_by_prov = defaultdict(list)  # {provider_name: [layers]}
        self.issues = list()
        self.qgis_files = None
        self.qgis_proj = None
        self.qgis_proj_path = None
        self.qgis_proj_dir = None
        self.changes = changes
        self.project_permission = project_permission
        self.layers_to_reset = None

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
        self.check_db_schema()
        self.check_project_relations()
        self.check_value_relation()
        self.check_field_names()
        self.check_snapping()
        self.check_datum_shift_grids()
        self.check_svgs_embedded()
        self.check_editor_perms()

        return self.issues

    def check_single_proj(self, project_dir):
        """Check if there is one and only one QGIS project in the directory."""
        self.qgis_files = find_qgis_files(project_dir)
        if len(self.qgis_files) > 1:
            self.issues.append(MultipleLayersWarning(Warning.MULTIPLE_PROJS))
            return False
        elif len(self.qgis_files) == 0:
            # might be deleted after opening in QGIS
            self.issues.append(MultipleLayersWarning(Warning.PROJ_NOT_FOUND))
            return False
        return True

    def check_proj_loaded(self):
        """Check if the QGIS project is loaded and validate it eventually. If not, no validation is done."""
        self.qgis_proj_path = self.qgis_files[0]
        loaded_proj_path = QgsProject.instance().absoluteFilePath()
        is_loaded = same_dir(self.qgis_proj_path, loaded_proj_path)
        if not is_loaded:
            self.issues.append(MultipleLayersWarning(Warning.PROJ_NOT_LOADED))
        else:
            self.qgis_proj = QgsProject.instance()
        return is_loaded

    def check_proj_paths_relative(self):
        """Check if the QGIS project has relative paths, i.e. not absolute ones."""
        abs_paths, ok = self.qgis_proj.readEntry("Paths", "/Absolute")
        assert ok
        if not abs_paths == "false":
            self.issues.append(MultipleLayersWarning(Warning.ABSOLUTE_PATHS))

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
            self.issues.append(MultipleLayersWarning(Warning.NO_EDITABLE_LAYERS))

    def check_editable_vectors_format(self):
        """Check if editable vector layers are GPKGs."""
        for lid, layer in self.layers.items():
            if lid not in self.editable:
                continue
            dp = layer.dataProvider()
            if not dp.storageType() == "GPKG":
                self.issues.append(SingleLayerWarning(lid, Warning.EDITABLE_NON_GPKG))

    def check_saved_in_proj_dir(self):
        """Check if layers saved in project's directory."""
        for lid, layer in self.layers.items():
            if lid not in self.layers_by_prov["gdal"] + self.layers_by_prov["ogr"]:
                continue
            pub_src = layer.publicSource()
            if pub_src.startswith("GPKG:"):
                pub_src = pub_src[5:]
                l_path = pub_src[: pub_src.rfind(":")]
            else:
                l_path = layer.publicSource().split("|")[0]
            l_dir = os.path.dirname(l_path)
            if not same_dir(l_dir, self.qgis_proj_dir):
                self.issues.append(SingleLayerWarning(lid, Warning.EXTERNAL_SRC))

    def check_offline(self):
        """Check if there are layers that might not be available when offline"""
        w = MultipleLayersWarning(Warning.NOT_FOR_OFFLINE)
        for lid, layer in self.layers.items():
            # special check for vector tile layers because in QGIS < 3.22 they may not have data provider assigned
            if layer.type() == QgsMapLayerType.VectorTileLayer:
                # mbtiles/vtpk are always local files
                if "type=mbtiles" in layer.source() or "type=vtpk" in layer.source():
                    continue
                w.items.append(layer.name())
                continue

            dp_name = layer.dataProvider().name()
            if dp_name in QGIS_NET_PROVIDERS + QGIS_DB_PROVIDERS:
                # raster tiles in mbtiles are always local files
                if dp_name == "wms" and "type=mbtiles" in layer.source():
                    continue
                w.items.append(layer.name())

        if w.items:
            self.issues.append(w)

    def check_attachment_widget(self):
        """Check if attachment widget is configured correctly."""
        for lid, layer in self.layers.items():
            if lid not in self.editable:
                continue
            fields = layer.fields()
            for i in range(fields.count()):
                ws = layer.editorWidgetSetup(i)
                if ws and ws.type() == "ExternalResource":
                    cfg = ws.config()
                    # check for relative paths
                    if "RelativeStorage" in cfg and cfg["RelativeStorage"] == 0:
                        self.issues.append(SingleLayerWarning(lid, Warning.ATTACHMENT_ABSOLUTE_PATH))
                    if "DefaultRoot" in cfg:
                        # default root should not be set to the local path
                        if os.path.isabs(cfg["DefaultRoot"]):
                            self.issues.append(SingleLayerWarning(lid, Warning.ATTACHMENT_LOCAL_PATH))

                        # expression-based path should be set with the data-defined overrride
                        expr = QgsExpression(cfg["DefaultRoot"])
                        if expr.isValid():
                            self.issues.append(SingleLayerWarning(lid, Warning.ATTACHMENT_EXPRESSION_PATH))

                        # using hyperlinks for document path is not allowed when
                        if "UseLink" in cfg:
                            self.issues.append(SingleLayerWarning(lid, Warning.ATTACHMENT_HYPERLINK))

                    # check that expression uses Mergin variables
                    try:
                        formula = cfg["PropertyCollection"]["properties"]["propertyRootPath"]["expression"]
                        if not PROJECT_VARS.search(formula):
                            self.issues.append(SingleLayerWarning(lid, Warning.ATTACHMENT_WRONG_EXPRESSION))
                    except (KeyError, TypeError):
                        continue

    def check_db_schema(self):
        for lid, layer in self.layers.items():
            if lid not in self.editable:
                continue
            dp = layer.dataProvider()
            if dp.storageType() == "GPKG":
                has_change, msg = has_schema_change(self.mp, layer)
                if has_change:
                    self.issues.append(SingleLayerWarning(lid, Warning.DATABASE_SCHEMA_CHANGE))

    def check_project_relations(self):
        """Check if project relations configured correctly"""
        relations = QgsProject.instance().relationManager().relations()
        for name, relation in relations.items():
            parent_layer = relation.referencedLayer()
            parent_fields = relation.referencedFields()
            child_layer = relation.referencingLayer()
            child_fields = relation.referencingFields()

            # check fields are unique
            self._check_field_unique(parent_layer, parent_fields)
            self._check_field_unique(child_layer, child_fields)

            # check that fields used in relation are not primary keys
            if parent_layer.dataProvider().storageType() == "GPKG":
                self._check_primary_keys(parent_layer, parent_fields)
            if child_layer.dataProvider().storageType() == "GPKG":
                self._check_primary_keys(child_layer, child_fields)

    def check_value_relation(self):
        """Check if value relation widget configured correctly."""
        for lid, layer in self.layers.items():
            if lid not in self.editable:
                continue
            fields = layer.fields()
            for i in range(fields.count()):
                ws = layer.editorWidgetSetup(i)
                if ws and ws.type() == "ValueRelation":
                    cfg = ws.config()
                    if "Layer" not in cfg or "Key" not in cfg:
                        self.issues.append(SingleLayerWarning(lid, Warning.BROKEN_VALUE_RELATION_CONFIG))
                        continue

                    child_layer = next((v for k, v in self.layers.items() if k == cfg["Layer"]), None)
                    if child_layer is None:
                        self.issues.append(SingleLayerWarning(lid, Warning.VALUE_RELATION_LAYER_MISSED))
                        continue

                    # check that "key" field does not have duplicated values
                    # and is not a primary key
                    if child_layer.dataProvider().storageType() == "GPKG":
                        idx = child_layer.fields().indexFromName(str(cfg["Key"]))
                        self._check_field_unique(child_layer, [idx])
                        self._check_primary_keys(child_layer, [idx])

    def _check_field_unique(self, layer, fields):
        feature_count = layer.dataProvider().featureCount()
        for f in fields:
            if len(layer.uniqueValues(f)) != feature_count:
                self.issues.append(SingleLayerWarning(layer.id(), Warning.KEY_FIELD_NOT_UNIQUE))

    def _check_primary_keys(self, layer, fields):
        layer_fields = layer.fields()
        keys = get_primary_keys(layer)
        for i in fields:
            if layer_fields[i].name() in keys:
                self.issues.append(SingleLayerWarning(layer.id(), Warning.FIELD_IS_PRIMARY_KEY))

    def check_field_names(self):
        for lid, layer in self.layers.items():
            if lid not in self.editable:
                continue
            dp = layer.dataProvider()
            if dp.storageType() == "GPKG":
                fields = layer.fields()
                for f in fields:
                    if INVALID_CHARS.search(f.name()):
                        self.issues.append(SingleLayerWarning(lid, Warning.INCORRECT_FIELD_NAME))

    def check_snapping(self):
        mode, ok = QgsProject.instance().readNumEntry("Mergin", "Snapping")
        if ok:
            enabled = QgsProject.instance().snappingConfig().enabled()
            if not enabled and mode == 2:
                # snapping in Input using QGIS setting is enbaled but QGIS snapping is not activated
                self.issues.append(MultipleLayersWarning(Warning.QGIS_SNAPPING_NOT_ENABLED))
            if enabled and mode == 0:
                # snapping in Input using QGIS setting is disabled but project has snapping activated
                self.issues.append(MultipleLayersWarning(Warning.MERGIN_SNAPPING_NOT_ENABLED))

    def check_datum_shift_grids(self):
        w = MultipleLayersWarning(Warning.MISSING_DATUM_SHIFT_GRID)
        grids = get_datum_shift_grids()
        proj_dir = project_grids_directory(self.mp)
        for grid in grids.keys():
            if proj_dir and not os.path.exists(os.path.join(proj_dir, grid)):
                w.items.append(grid)

        if w.items:
            self.issues.append(w)

    def check_svgs_embedded(self):
        for lid, layer in self.layers.items():
            if layer.type() != QgsMapLayerType.VectorLayer:
                continue

            renderer = layer.renderer()
            if renderer is None:
                continue

            context = QgsRenderContext()
            symbols = renderer.symbols(context)
            not_embedded = False
            for sym in symbols:
                for sym_layer in sym.symbolLayers():
                    if sym_layer.layerType() != "SvgMarker":
                        continue

                    if self.qgis_proj_dir is not None:
                        if not sym_layer.path().startswith(self.qgis_proj_dir) and not sym_layer.path().startswith(
                            "base64:"
                        ):
                            not_embedded = True
                            break
                    else:
                        if not sym_layer.path().startswith("base64:"):
                            not_embedded = True
                            break

                if not_embedded:
                    self.issues.append(SingleLayerWarning(lid, Warning.SVG_NOT_EMBEDDED))
                    break

    def check_editor_perms(self):
        if self.project_permission == "editor":
            # check if project file has changed
            for file in self.changes["updated"]:
                if file["path"].lower().endswith(('.qgs', '.qgz')):
                    url = f"#reset_qgs_file?{file['path']}"
                    self.issues.append(MultipleLayersWarning(Warning.EDITOR_PROJECT_FILE_CHANGE, url))
            # check changes are diff-based not override
            for lid, layer in self.layers.items():
                if lid not in self.editable:
                    continue
                dp = layer.dataProvider()
                if dp.storageType() == "GPKG":
                    has_change, msg = has_schema_change(self.mp, layer)
                    if has_change:
                        layer_path = layer.dataProvider().dataSourceUri().split("/")[-1]
                        url = f"#reset_layer?{layer_path}"
                        self.issues.append(SingleLayerWarning(lid, Warning.EDITOR_NON_DIFFABLE_CHANGE, url))
                else:
                    layer_path = layer.dataProvider().dataSourceUri().split("/")[-1]
                    url = f"#reset_layer?{layer_path}"
                    self.issues.append(SingleLayerWarning(lid, Warning.EDITOR_NON_DIFFABLE_CHANGE, url))
            # TODO: check mergin-config.json has changed


def warning_display_string(warning_id, url=None):
    """Returns a display string for a corresponding warning"""
    help_mgr = MerginHelp()
    if warning_id == Warning.PROJ_NOT_LOADED:
        return "The QGIS project is not loaded. Open it to allow validation"
    elif warning_id == Warning.PROJ_NOT_FOUND:
        return "No QGIS project found in the directory"
    elif warning_id == Warning.MULTIPLE_PROJS:
        return "Multiple QGIS project files found in the directory"
    elif warning_id == Warning.ABSOLUTE_PATHS:
        return "QGIS project saves layers using absolute paths"
    elif warning_id == Warning.EDITABLE_NON_GPKG:
        return "Editable layer stored in a format other than GeoPackage"
    elif warning_id == Warning.EXTERNAL_SRC:
        return "Layer stored out of the project directory"
    elif warning_id == Warning.NOT_FOR_OFFLINE:
        return f"Layer might not be available when offline. <a href='{help_mgr.howto_background_maps()}'>Read more.</a>"
    elif warning_id == Warning.NO_EDITABLE_LAYERS:
        return "No editable layers in the project"
    elif warning_id == Warning.ATTACHMENT_ABSOLUTE_PATH:
        return f"Attachment widget uses absolute paths. <a href='{help_mgr.howto_attachment_widget()}'>Read more.</a>"
    elif warning_id == Warning.ATTACHMENT_LOCAL_PATH:
        return "Attachment widget uses local path"
    elif warning_id == Warning.ATTACHMENT_EXPRESSION_PATH:
        return "Attachment widget incorrectly uses expression-based path"
    elif warning_id == Warning.ATTACHMENT_HYPERLINK:
        return "Attachment widget uses hyperlink"
    elif warning_id == Warning.DATABASE_SCHEMA_CHANGE:
        return "Database schema was changed"
    elif warning_id == Warning.KEY_FIELD_NOT_UNIQUE:
        return "Relation key field contains duplicated values"
    elif warning_id == Warning.FIELD_IS_PRIMARY_KEY:
        return "Relation uses primary key field"
    elif warning_id == Warning.VALUE_RELATION_LAYER_MISSED:
        return "Referenced table is missed from the project"
    elif warning_id == Warning.INCORRECT_FIELD_NAME:
        return "Field names contain line-break characters"
    elif warning_id == Warning.BROKEN_VALUE_RELATION_CONFIG:
        return "Incomplete value relation configuration"
    elif warning_id == Warning.ATTACHMENT_WRONG_EXPRESSION:
        return "Expression for the default path in the attachment widget configuration might be wrong. <a href='{help_mgr.howto_attachment_widget()}'>Read more.</a>"
    elif warning_id == Warning.QGIS_SNAPPING_NOT_ENABLED:
        return "Snapping is currently disabled in this QGIS project, it will be thus disabled in Mergin Maps Input"
    elif warning_id == Warning.MERGIN_SNAPPING_NOT_ENABLED:
        return "Snapping is currently enabled in this QGIS project, but not enabled in Mergin Maps Input"
    elif warning_id == Warning.MISSING_DATUM_SHIFT_GRID:
        return "Required datum shift grid is missing, reprojection may not work correctly. <a href='#fix_datum_shift_grids'>Fix the issue.</a>"
    elif warning_id == Warning.SVG_NOT_EMBEDDED:
        return "SVGs used for layer styling are not embedded in the project file, as a result those symbols won't be displayed in Mergin Maps Input"
    elif warning_id == Warning.EDITOR_PROJECT_FILE_CHANGE:
        return f"You don't have permission to edit QGS project file. Ask workspace admin to upgrade you permission or <a href='{url}'>reset QGS project file</a> to be able to sync data changes. This might involve deleting layers you created locally."
    elif warning_id == Warning.EDITOR_NON_DIFFABLE_CHANGE:
        return f"You don't have permission to edit layer schema. Ask workspace admin to upgrade you permission or <a href='{url}'>reset the layer</a> to be able to sync changes in other layers."
