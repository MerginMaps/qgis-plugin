# -*- coding: utf-8 -*-

import os
import sqlite3
import shutil

from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingUtils,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingParameterFile,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterFeatureSink,
)

from ..postprocessors import StylingPostProcessor

from ...mergin.merginproject import MerginProject
from ...mergin.utils import get_versions_with_file_changes

from ...diff import parse_db_schema, parse_diff, get_table_name, create_field_list, diff_table_to_features

from ...utils import (
    icon_path,
    create_mergin_client,
    check_mergin_subdirs,
)


class CreateDiff(QgsProcessingAlgorithm):

    PROJECT_DIR = "PROJECT_DIR"
    LAYER = "LAYER"
    START_VERSION = "START_VERSION"
    END_VERSION = "END_VERSION"
    OUTPUT = "OUTPUT"

    def name(self):
        return "creatediff"

    def displayName(self):
        return "Create diff"

    def group(self):
        return "Tools"

    def groupId(self):
        return "tools"

    def tags(self):
        return "mergin,added,dropped,new,deleted,features,geometries,difference,delta,revised,original,version,compare".split(
            ","
        )

    def shortHelpString(self):
        return "Extracts changes made between two versions of the layer of the Mergin project to make it easier to revise changes."

    def icon(self):
        return QIcon(icon_path("mm_icon_positive_no_padding.svg"))

    def __init__(self):
        super().__init__()

    def createInstance(self):
        return type(self)()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(self.PROJECT_DIR, "Project directory", QgsProcessingParameterFile.Folder)
        )
        self.addParameter(QgsProcessingParameterVectorLayer(self.LAYER, "Input layer"))
        self.addParameter(
            QgsProcessingParameterNumber(
                self.START_VERSION, "Start version", QgsProcessingParameterNumber.Integer, 1, False, 1
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.END_VERSION, "End version", QgsProcessingParameterNumber.Integer, None, True, 1
            )
        )
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, "Diff layer"))

    def processAlgorithm(self, parameters, context, feedback):
        project_dir = self.parameterAsString(parameters, self.PROJECT_DIR, context)
        layer = self.parameterAsVectorLayer(parameters, self.LAYER, context)

        if not check_mergin_subdirs(project_dir):
            raise QgsProcessingException("Selected directory does not contain a valid Mergin project.")

        if not os.path.normpath(layer.source()).lower().startswith(os.path.normpath(project_dir)):
            raise QgsProcessingException("Selected layer does not belong to the selected Mergin project.")

        if layer.dataProvider().storageType() != "GPKG":
            raise QgsProcessingException("Selected layer not supported.")

        start = self.parameterAsInt(parameters, self.START_VERSION, context)
        if self.END_VERSION in parameters and parameters[self.END_VERSION] is not None:
            end = self.parameterAsInt(parameters, self.END_VERSION, context)
        else:
            end = ""

        table_name = get_table_name(layer)
        layer_path = layer.source().split("|")[0]
        file_name = os.path.split(layer_path)[1]

        mc = create_mergin_client()
        mp = MerginProject(project_dir)

        feedback.pushInfo("Downloading base file…")
        base_file = QgsProcessingUtils.generateTempFilename(file_name)
        mc.download_file(project_dir, file_name, base_file, f"v{end}" if end else None)
        feedback.setProgress(10)

        diff_file = QgsProcessingUtils.generateTempFilename(file_name + ".diff")
        mc.get_file_diff(project_dir, file_name, diff_file, f"v{start}", f"v{end}" if end else None)
        feedback.setProgress(20)

        feedback.pushInfo("Parse schema…")
        db_schema = parse_db_schema(base_file)
        feedback.setProgress(25)

        feedback.pushInfo("Create field list…")
        fields, fields_mapping = create_field_list(db_schema[table_name])
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, layer.wkbType(), layer.sourceCrs()
        )

        feedback.pushInfo("Parse diff…")
        diff = parse_diff(diff_file)
        feedback.setProgress(30)

        if diff and table_name in diff.keys():
            db_conn = None  # no ref. db
            db_conn = sqlite3.connect(layer_path)
            features = diff_table_to_features(diff[table_name], db_schema[table_name], fields, fields_mapping, db_conn)
            feedback.setProgress(40)

            current = 40
            step = 60.0 / len(features) if features else 0
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
