import json
import os
from qgis.PyQt import uic
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QFileDialog
from qgis.core import (
    QgsProject,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeature,
    QgsFeatureRequest,
    QgsExpression,
)
from qgis.gui import QgsOptionsWidgetFactory, QgsOptionsPageWidget
from .attachment_fields_model import AttachmentFieldsModel
from .utils import icon_path, mergin_project_local_path, prefix_for_relative_path, resolve_target_dir

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_project_config.ui")
ProjectConfigUiWidget, _ = uic.loadUiType(ui_file)


class MerginProjectConfigFactory(QgsOptionsWidgetFactory):
    def __init__(self):
        QgsOptionsWidgetFactory.__init__(self)

    def icon(self):
        return QIcon(icon_path("mm_icon_positive_no_padding.svg"))

    def title(self):
        return "Mergin Maps"

    def createWidget(self, parent):
        return ProjectConfigWidget(parent)


class ProjectConfigWidget(ProjectConfigUiWidget, QgsOptionsPageWidget):
    def __init__(self, parent=None):
        QgsOptionsPageWidget.__init__(self, parent)
        self.setupUi(self)

        self.cmb_photo_quality.addItem("Original", 0)
        self.cmb_photo_quality.addItem("High (approx. 2-4 Mb)", 1)
        self.cmb_photo_quality.addItem("Medium (approx. 1-2 Mb)", 2)
        self.cmb_photo_quality.addItem("Low (approx. 0.5 Mb)", 3)

        quality, ok = QgsProject.instance().readNumEntry("Mergin", "PhotoQuality")
        idx = self.cmb_photo_quality.findData(quality) if ok else 0
        self.cmb_photo_quality.setCurrentIndex(idx if idx > 0 else 0)

        self.cmb_snapping_mode.addItem("No snapping", 0)
        self.cmb_snapping_mode.addItem("Basic snapping", 1)
        self.cmb_snapping_mode.addItem("Follow QGIS snapping", 2)

        mode, ok = QgsProject.instance().readNumEntry("Mergin", "Snapping")
        idx = self.cmb_snapping_mode.findData(mode) if ok else 0
        self.cmb_snapping_mode.setCurrentIndex(idx if idx > 0 else 0)

        self.local_project_dir = mergin_project_local_path()

        if self.local_project_dir:
            self.config_file = os.path.join(self.local_project_dir, "mergin-config.json")
            self.load_config_file()
            self.btn_get_sync_dir.clicked.connect(self.get_sync_dir)
        else:
            self.selective_sync_group.setEnabled(False)

        self.attachments_model = AttachmentFieldsModel()
        self.attachment_fields.setModel(self.attachments_model)
        self.attachment_fields.selectionModel().currentChanged.connect(self.update_expression_edit)
        self.edit_photo_expression.expressionChanged.connect(self.expression_changed)

    def get_sync_dir(self):
        abs_path = QFileDialog.getExistingDirectory(
            None, "Select directory", self.local_project_dir, QFileDialog.ShowDirsOnly
        )
        if self.local_project_dir not in abs_path:
            return
        dir_path = abs_path.replace(self.local_project_dir, "").lstrip("/")
        self.edit_sync_dir.setText(dir_path)

    def load_config_file(self):
        if not self.local_project_dir or not os.path.exists(self.config_file):
            return

        with open(self.config_file, "r") as f:
            config = json.load(f)
            self.edit_sync_dir.setText(config["input-selective-sync-dir"])
            self.chk_sync_enabled.setChecked(config["input-selective-sync"])

    def save_config_file(self):
        if not self.local_project_dir:
            return

        if os.path.exists(self.config_file):
            with open(self.config_file, "r") as f:
                config = json.load(f)
        else:
            config = {}

        config["input-selective-sync"] = self.chk_sync_enabled.isChecked()
        config["input-selective-sync-dir"] = self.edit_sync_dir.text()

        with open(self.config_file, "w") as f:
            json.dump(config, f, indent=2)

    def expression_changed(self, expression):
        if not self.attachment_fields.selectionModel().hasSelection():
            return
        index = self.attachment_fields.selectionModel().selectedIndexes()[0]
        layer = None
        field_name = None
        if index.isValid():
            item = self.attachments_model.item(index.row(), 1)
            item.setData(self.edit_photo_expression.expression(), AttachmentFieldsModel.EXPRESSION)
            layer = QgsProject.instance().mapLayer(item.data(AttachmentFieldsModel.LAYER_ID))
            field_name = item.data(AttachmentFieldsModel.FIELD_NAME)

        self.update_preview(expression, layer, field_name)

    def update_expression_edit(self, current, previous):
        item = self.attachments_model.item(current.row(), 1)
        exp = item.data(AttachmentFieldsModel.EXPRESSION)
        field_name = item.data(AttachmentFieldsModel.FIELD_NAME)
        layer = QgsProject.instance().mapLayer(item.data(AttachmentFieldsModel.LAYER_ID))
        if layer and layer.isValid():
            self.edit_photo_expression.setLayer(layer)

        self.edit_photo_expression.blockSignals(True)
        self.edit_photo_expression.setExpression(exp if exp else "")
        self.edit_photo_expression.blockSignals(False)
        self.update_preview(exp, layer, field_name)

    def update_preview(self, expression, layer, field_name):
        if expression == "":
            self.label_preview.setText("")
            return

        context = None
        if layer and layer.isValid():
            context = layer.createExpressionContext()
            f = QgsFeature()
            layer.getFeatures(QgsFeatureRequest().setLimit(1)).nextFeature(f)
            if f.isValid():
                context.setFeature(f)
        else:
            context = QgsExpressionContext()
            context.appendScope(QgsExpressionContextUtils.globalScope())
            context.appendScope(QgsExpressionContextUtils.projectScope(QgsProject.instance()))

        exp = QgsExpression(expression)
        exp.prepare(context)
        if exp.hasParserError():
            self.label_preview.setText(f"<i>{exp.parserErrorString()}</i>")
            return

        val = exp.evaluate(context)
        if exp.hasEvalError():
            self.label_preview.setText(f"<i>{exp.evalErrorString()}</i>")
            return

        config = layer.fields().field(field_name).editorWidgetSetup().config()
        target_dir = resolve_target_dir(layer, config)
        prefix = prefix_for_relative_path(
            config.get("RelativeStorage", 0), QgsProject.instance().homePath(), target_dir
        )
        if prefix:
            self.label_preview.setText(f"<i>{prefix.removeprefix(QgsProject.instance().homePath())}/{val}.jpg</i>")
        else:
            self.label_preview.setText(f"<i>{val}.jpg</i>")

    def apply(self):
        QgsProject.instance().writeEntry("Mergin", "PhotoQuality", self.cmb_photo_quality.currentData())
        QgsProject.instance().writeEntry("Mergin", "Snapping", self.cmb_snapping_mode.currentData())
        for i in range(self.attachments_model.rowCount()):
            index = self.attachments_model.index(i, 1)
            if index.isValid():
                item = self.attachments_model.itemFromIndex(index)
                layer_id = item.data(AttachmentFieldsModel.LAYER_ID)
                field_name = item.data(AttachmentFieldsModel.FIELD_NAME)
                expression = item.data(AttachmentFieldsModel.EXPRESSION)
                QgsProject.instance().writeEntry("Mergin", f"PhotoNaming/{layer_id}/{field_name}", expression)

        self.save_config_file()
