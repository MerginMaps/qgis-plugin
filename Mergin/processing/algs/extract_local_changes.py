# -*- coding: utf-8 -*-

import os
import sqlite3

from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingParameterFile,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterFeatureSink,
)

from ..postprocessors import StylingPostProcessor

from ...mergin.merginproject import MerginProject
from ...mergin.deps import pygeodiff
from ...diff import (
    get_local_changes,
    parse_db_schema,
    parse_diff,
    get_table_name,
    create_field_list,
    diff_table_to_features,
)

from ...utils import (
    mm_symbol_path,
    check_mergin_subdirs,
)


class ExtractLocalChanges(QgsProcessingAlgorithm):
    PROJECT_DIR = "PROJECT_DIR"
    LAYER = "LAYER"
    OUTPUT = "OUTPUT"

    def name(self):
        return "extractlocalchanges"

    def displayName(self):
        return "Extract local changes"

    def group(self):
        return "Tools"

    def groupId(self):
        return "tools"

    def tags(self):
        return "mergin,added,dropped,new,deleted,features,geometries,difference,delta,revised,original,version,compare".split(
            ","
        )

    def shortHelpString(self):
        return "Extracts local changes made in the specific layer of the Mergin Maps project to make it easier to revise changes."

    def icon(self):
        return QIcon(mm_symbol_path())

    def __init__(self):
        super().__init__()

    def createInstance(self):
        return type(self)()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(self.PROJECT_DIR, "Project directory", QgsProcessingParameterFile.Folder)
        )
        self.addParameter(QgsProcessingParameterVectorLayer(self.LAYER, "Input layer"))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, "Local changes layer"))

    def processAlgorithm(self, parameters, context, feedback):
        project_dir = self.parameterAsString(parameters, self.PROJECT_DIR, context)
        layer = self.parameterAsVectorLayer(parameters, self.LAYER, context)

        if not check_mergin_subdirs(project_dir):
            raise QgsProcessingException("Selected directory does not contain a valid Mergin project.")

        if not os.path.normpath(layer.source()).lower().startswith(os.path.normpath(project_dir).lower()):
            raise QgsProcessingException("Selected layer does not belong to the selected Mergin project.")

        if layer.dataProvider().storageType() != "GPKG":
            raise QgsProcessingException("Selected layer not supported.")

        mp = MerginProject(project_dir)

        geodiff = pygeodiff.GeoDiff()

        layer_path = layer.source().split("|")[0]
        diff_path = get_local_changes(geodiff, layer_path, mp)
        feedback.setProgress(5)

        if diff_path is None:
            raise QgsProcessingException("Failed to get local changes.")

        table_name = get_table_name(layer)

        db_schema = parse_db_schema(layer_path)
        feedback.setProgress(10)

        fields, fields_mapping = create_field_list(db_schema[table_name])
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, layer.wkbType(), layer.sourceCrs()
        )

        diff = parse_diff(geodiff, diff_path)
        feedback.setProgress(15)

        if diff and table_name in diff.keys():
            db_conn = None  # no ref. db
            db_conn = sqlite3.connect(layer_path)
            features = diff_table_to_features(diff[table_name], db_schema[table_name], fields, fields_mapping, db_conn)
            feedback.setProgress(20)

            current = 20
            step = 80.0 / len(features) if features else 0
            for i, f in enumerate(features):
                if feedback.isCanceled():
                    break
                sink.addFeature(f, QgsFeatureSink.FastInsert)
                feedback.setProgress(int(i * step))

        if context.willLoadLayerOnCompletion(dest_id):
            context.layerToLoadOnCompletionDetails(dest_id).setPostProcessor(
                StylingPostProcessor.create(db_schema[table_name])
            )

        return {self.OUTPUT: dest_id}
