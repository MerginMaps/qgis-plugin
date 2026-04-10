# GPLv3 license
# Copyright Lutra Consulting Limited

import json
import os
import typing
from functools import partial

from qgis.PyQt import uic
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtCore import Qt, QModelIndex
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMenu, QMessageBox, QGroupBox, QComboBox
from qgis.core import (
    QgsProject,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeature,
    QgsFeatureRequest,
    QgsExpression,
    QgsMapLayer,
    QgsVectorLayer,
    QgsFieldProxyModel,
)
from qgis.gui import (
    QgsOptionsWidgetFactory,
    QgsOptionsPageWidget,
    QgsColorButton,
    QgsMapLayerComboBox,
    QgsFieldComboBox,
)
from .attachment_fields_model import AttachmentFieldsModel
from .utils import (
    mm_symbol_path,
    mergin_project_local_path,
    prefix_for_relative_path,
    resolve_target_dir,
    create_tracking_layer,
    create_map_sketches_layer,
    set_tracking_layer_flags,
    remove_prefix,
    invalid_filename_character,
    qvariant_to_string,
    escape_html_minimal,
    sanitize_path,
)
from .field_filtering import (
    FieldFilterType,
    FieldFilter,
    FieldFilterModel,
    DeselectableListView,
    excluded_filtering_providers,
)

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_project_config.ui")
ProjectConfigUiWidget, _ = uic.loadUiType(ui_file)


class MerginProjectConfigFactory(QgsOptionsWidgetFactory):
    def __init__(self):
        QgsOptionsWidgetFactory.__init__(self)

    def icon(self):
        return QIcon(mm_symbol_path())

    def title(self):
        return "Mergin Maps"

    def createWidget(self, parent):
        return ProjectConfigWidget(parent)


class ProjectConfigWidget(ProjectConfigUiWidget, QgsOptionsPageWidget):

    cmb_filter_type: QComboBox
    cmb_filter_layer: QgsMapLayerComboBox
    cmb_filter_field: QgsFieldComboBox
    groupBox_filters_list: QGroupBox
    groupBox_filter_detail: QGroupBox

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

        enabled, ok = QgsProject.instance().readBoolEntry("Mergin", "PositionTracking/Enabled")
        if ok:
            self.chk_tracking_enabled.setChecked(enabled)
        else:
            self.chk_tracking_enabled.setChecked(False)
        self.chk_tracking_enabled.stateChanged.connect(self.check_project)

        self.cmb_tracking_precision.addItem("Best", 0)
        self.cmb_tracking_precision.addItem("Normal", 1)
        self.cmb_tracking_precision.addItem("Low", 2)

        mode, ok = QgsProject.instance().readNumEntry("Mergin", "PositionTracking/UpdateFrequency")
        idx = self.cmb_tracking_precision.findData(mode) if ok else 1
        self.cmb_tracking_precision.setCurrentIndex(idx)

        enabled, _ = QgsProject.instance().readBoolEntry("Mergin", "PhotoSketching/Enabled", False)
        self.chk_photo_sketching_enabled.setChecked(enabled)

        enabled, ok = QgsProject.instance().readBoolEntry("Mergin", "MapSketching/Enabled")

        if ok:
            self.chk_map_sketches_enabled.setChecked(enabled)
        else:
            self.chk_map_sketches_enabled.setChecked(False)

        self.colors_change_state()
        self.chk_map_sketches_enabled.stateChanged.connect(self.colors_change_state)

        colors, ok = QgsProject.instance().readListEntry("Mergin", "MapSketching/Colors")
        if ok:
            for i in range(self.mColorsHorizontalLayout.count()):
                item = self.mColorsHorizontalLayout.itemAt(i).widget()
                if isinstance(item, QgsColorButton):
                    if i < len(colors):
                        item.setColor(QColor(colors[i]))
                    else:
                        item.setColor(QColor("#ffffff"))

        self.cmb_sort_method.addItem("QGIS layer order", 0)
        self.cmb_sort_method.addItem("Alphabetical", 1)

        mode, ok = QgsProject.instance().readNumEntry("Mergin", "SortLayersMethod/Method")
        idx = self.cmb_sort_method.findData(mode) if ok else 1
        self.cmb_sort_method.setCurrentIndex(idx)

        self.filters_model = FieldFilterModel()
        self.btn_add_filter.clicked.connect(self.on_add_filter_clicked)
        self.btn_remove_filter.clicked.connect(self.on_remove_filter_clicked)
        self.btn_move_filter_up.clicked.connect(self.on_move_filter_up_clicked)
        self.btn_move_filter_down.clicked.connect(self.on_move_filter_down_clicked)

        add_filter_menu = QMenu(self)
        for filter_type in FieldFilterType:
            action = QAction(filter_type.value, self)
            action.triggered.connect(partial(self.add_unnamed_filter, filter_type))
            add_filter_menu.addAction(action)
        self.btn_add_filter.setMenu(add_filter_menu)

        self.lst_filters = DeselectableListView(self)
        self.groupBox_filters_list.layout().insertWidget(0, self.lst_filters)
        self.lst_filters.setModel(self.filters_model)
        self.lst_filters.selectionCleared.connect(self.on_filter_selection_removed)
        self.lst_filters.selectionModel().selectionChanged.connect(self._update_filter_buttons)
        self.lst_filters.selectionModel().currentChanged.connect(self.on_filter_selection_changed)

        enabled, _ = QgsProject.instance().readBoolEntry("Mergin", "Filtering/Enabled", False)
        self.chk_filtering_enabled.setChecked(enabled)
        self.groupBox_filters_list.setEnabled(enabled)
        self.chk_filtering_enabled.stateChanged.connect(self.on_filtering_state_changed)

        filters_json, _ = QgsProject.instance().readEntry("Mergin", "Filtering/Filters", "[]")
        self.filters_model.load_from_json(filters_json)

        self.cmb_filter_layer.setAllowEmptyLayer(True)
        self.cmb_filter_layer.setExcludedProviders(excluded_filtering_providers())
        self.cmb_filter_layer.layerChanged.connect(self.on_filter_layer_fields_changed)

        for f in FieldFilterType:
            self.cmb_filter_type.addItem(f.value, f)
        self.cmb_filter_type.currentIndexChanged.connect(self.on_filter_layer_fields_changed)

        # update existing FieldFilter on edits
        self.cmb_filter_layer.layerChanged.connect(self.on_filter_detail_changed)
        self.cmb_filter_type.currentIndexChanged.connect(self.on_filter_detail_changed)
        self.cmb_filter_field.fieldChanged.connect(self.on_filter_detail_changed)
        self.edit_filter_title.textChanged.connect(self.on_filter_detail_changed)

        self._update_filter_buttons()
        self.on_filter_layer_fields_changed()

        # clear filter values and disable filter details until we load actual filter from list view
        self._clear_filter_values()
        self.groupBox_filter_detail.setEnabled(False)

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
            None,
            "Select directory",
            self.local_project_dir,
            QFileDialog.Option.ShowDirsOnly,
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
            expr = self.edit_photo_expression.expression()
            clean_expr = sanitize_path(expr)
            item.setData(clean_expr, AttachmentFieldsModel.EXPRESSION)
            layer = QgsProject.instance().mapLayer(item.data(AttachmentFieldsModel.LAYER_ID))
            field_name = item.data(AttachmentFieldsModel.FIELD_NAME)

        self.update_preview(clean_expr, layer, field_name)

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
        if not expression:
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
            self.label_preview.setText(exp.parserErrorString())
            return

        val = exp.evaluate(context)
        if exp.hasEvalError():
            self.label_preview.setText(exp.evalErrorString())
            return

        str_val = qvariant_to_string(val)
        if not str_val:
            self.label_preview.setText("")
            return

        invalid_char = invalid_filename_character(str_val)
        filename_display = escape_html_minimal(str_val)
        if invalid_char:
            invalid_char_display = escape_html_minimal(invalid_char)
            self.label_preview.setText(
                f"The file name '{filename_display}.jpg' contains an invalid character. Do not use '{invalid_char_display}' character in the file name."
            )
            return

        config = layer.fields().field(field_name).editorWidgetSetup().config()
        target_dir = resolve_target_dir(layer, config)
        prefix = prefix_for_relative_path(
            config.get("RelativeStorage", 0),
            QgsProject.instance().homePath(),
            target_dir,
        )
        if prefix:
            self.label_preview.setText(
                f"{remove_prefix(prefix, QgsProject.instance().homePath())}/{filename_display}.jpg"
            )
        else:
            self.label_preview.setText(f"{filename_display}.jpg")

    def check_project(self, state):
        """
        Check whether project is saved and we can create tracking
        layer for it.
        """
        if QgsProject.instance().absolutePath() == "":
            QMessageBox.warning(
                self,
                "Project is not saved",
                "It seems that your project is not saved yet, please save "
                "project before enabling tracking as we need to know where "
                "to place required files.",
            )
            self.chk_tracking_enabled.blockSignals(True)
            self.chk_tracking_enabled.setCheckState(Qt.CheckState.Unchecked)
            self.chk_tracking_enabled.blockSignals(False)

    def setup_tracking(self):
        if self.chk_tracking_enabled.checkState() == Qt.CheckState.Unchecked:
            return

        # check if tracking layer already exists
        tracking_layer_id, ok = QgsProject.instance().readEntry("Mergin", "PositionTracking/TrackingLayer")
        if tracking_layer_id != "" and tracking_layer_id in QgsProject.instance().mapLayers():
            # tracking layer already exists in the project, make sure it has correct flags
            layer = QgsProject.instance().mapLayers()[tracking_layer_id]
            if layer is not None and layer.isValid():
                set_tracking_layer_flags(layer)
            return

        # tracking layer does not exists or was removed from the project
        # create a new layer and add it as a tracking layer
        create_tracking_layer(QgsProject.instance().absolutePath())

    def setup_map_sketches(self):
        if self.chk_map_sketches_enabled.checkState() == Qt.CheckState.Unchecked:
            return

        # check if map sketches layer already exists
        map_sketches_layer_id, ok = QgsProject.instance().readEntry("Mergin", "MapSketching/Layer")

        if map_sketches_layer_id != "" and map_sketches_layer_id in QgsProject.instance().mapLayers():
            # map sketches layer already exists in the project, make sure it has correct flags
            layer = QgsProject.instance().mapLayers()[map_sketches_layer_id]
            if layer is not None and layer.isValid():
                layer.setReadOnly(False)
                layer.setFlags(
                    QgsMapLayer.LayerFlag(QgsMapLayer.Identifiable + QgsMapLayer.Searchable + QgsMapLayer.Removable)
                )

        else:
            # map sketches layer does not exists or was removed from the project
            # create a new layer and add it as a map sketches layer
            create_map_sketches_layer(QgsProject.instance().absolutePath())

    def apply(self):
        QgsProject.instance().writeEntry("Mergin", "PhotoQuality", self.cmb_photo_quality.currentData())
        QgsProject.instance().writeEntry("Mergin", "Snapping", self.cmb_snapping_mode.currentData())
        QgsProject.instance().writeEntry("Mergin", "PositionTracking/Enabled", self.chk_tracking_enabled.isChecked())
        QgsProject.instance().writeEntry(
            "Mergin",
            "PositionTracking/UpdateFrequency",
            self.cmb_tracking_precision.currentData(),
        )

        QgsProject.instance().writeEntry(
            "Mergin",
            "PhotoSketching/Enabled",
            self.chk_photo_sketching_enabled.isChecked(),
        )

        QgsProject.instance().writeEntry("Mergin", "MapSketching/Enabled", self.chk_map_sketches_enabled.isChecked())

        colors: typing.List[str] = []
        for i in range(self.mColorsHorizontalLayout.count()):
            item = self.mColorsHorizontalLayout.itemAt(i).widget()
            if isinstance(item, QgsColorButton):
                color = item.color().name()
                if color:
                    colors.append(color)
        QgsProject.instance().writeEntry("Mergin", "MapSketching/Colors", colors)

        for i in range(self.attachments_model.rowCount()):
            index = self.attachments_model.index(i, 1)
            if index.isValid():
                item = self.attachments_model.itemFromIndex(index)
                layer_id = item.data(AttachmentFieldsModel.LAYER_ID)
                field_name = item.data(AttachmentFieldsModel.FIELD_NAME)
                expression = item.data(AttachmentFieldsModel.EXPRESSION)
                QgsProject.instance().writeEntry("Mergin", f"PhotoNaming/{layer_id}/{field_name}", expression)

        QgsProject.instance().writeEntry("Mergin", "SortLayersMethod/Method", self.cmb_sort_method.currentData())
        self.save_config_file()
        self.setup_tracking()
        self.setup_map_sketches()

        QgsProject.instance().writeEntry("Mergin", "Filtering/Enabled", self.chk_filtering_enabled.isChecked())
        QgsProject.instance().writeEntry("Mergin", "Filtering/Filters", self.filters_model.to_json())

    def colors_change_state(self) -> None:
        """
        Enable/disable color buttons based on the state of the map sketches checkbox.
        """
        for i in range(self.mColorsHorizontalLayout.count()):
            item = self.mColorsHorizontalLayout.itemAt(i).widget()
            if isinstance(item, QgsColorButton):
                item.setEnabled(self.chk_map_sketches_enabled.isChecked())

    def on_filtering_state_changed(self, state: Qt.CheckState) -> None:
        """
        Enable/disable filtering options based on the state of the filtering checkbox.
        """
        if state == Qt.CheckState.Checked:
            self.groupBox_filters_list.setEnabled(True)
            self.groupBox_filter_detail.setEnabled(True)
            fields_enabled = False
            if self.lst_filters.selectedIndexes():
                fields_enabled = self.lst_filters.selectedIndexes()[0].isValid()
            self.cmb_filter_type.setEnabled(fields_enabled)
            self.cmb_filter_layer.setEnabled(fields_enabled)
            self.cmb_filter_field.setEnabled(fields_enabled)
            self.edit_filter_title.setEnabled(fields_enabled)
        else:
            self.groupBox_filters_list.setEnabled(False)
            self.groupBox_filter_detail.setEnabled(False)

    def on_add_filter_clicked(self) -> None:
        layer = self.cmb_filter_layer.currentLayer()
        field_name = self.cmb_filter_field.currentField()
        filter_type = self.cmb_filter_type.currentData()
        filter_name = self.edit_filter_title.text().strip()

        if not layer or not layer.isValid():
            return
        if not field_name:
            return
        if not filter_name:
            return

        self.filters_model.add_filter(
            FieldFilter(
                layer=layer,
                field_name=field_name,
                filter_type=filter_type,
                filter_name=filter_name,
            )
        )

    def _clear_filter_values(self) -> None:
        self.cmb_filter_layer.setLayer(None)
        self.cmb_filter_field.setLayer(None)
        self.cmb_filter_type.setCurrentIndex(0)
        self.edit_filter_title.clear()

    def on_filter_selection_removed(self, selected: QModelIndex, previous: QModelIndex) -> None:
        self.groupBox_filter_detail.setEnabled(False)
        self._clear_filter_values()

    def on_filter_selection_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        field_filter: typing.Optional[FieldFilter] = self.filters_model.data(current, Qt.ItemDataRole.UserRole)
        if field_filter is None:
            self._clear_filter_values()
            return

        self.cmb_filter_type.setEnabled(True)
        self.cmb_filter_layer.setEnabled(True)
        self.cmb_filter_field.setEnabled(True)
        self.edit_filter_title.setEnabled(True)

        self.groupBox_filter_detail.setEnabled(True)

        layer = QgsProject.instance().mapLayer(field_filter.layer_id)

        self.cmb_filter_layer.blockSignals(True)
        self.cmb_filter_layer.setLayer(layer)
        self.cmb_filter_layer.blockSignals(False)

        self.cmb_filter_field.blockSignals(True)
        self.cmb_filter_field.setLayer(layer)
        self.cmb_filter_field.setField(field_filter.field_name)
        self.cmb_filter_field.blockSignals(False)

        idx = self.cmb_filter_type.findData(field_filter.filter_type)
        self.cmb_filter_type.blockSignals(True)
        self.cmb_filter_type.setCurrentIndex(idx)
        self.cmb_filter_type.blockSignals(False)

        # block signals to avoid triggering modification of the field filter
        self.edit_filter_title.blockSignals(True)
        self.edit_filter_title.setText(field_filter.filter_name)
        self.edit_filter_title.blockSignals(False)

    def _update_filter_buttons(self) -> None:
        has_selection = self.lst_filters.selectionModel().hasSelection()
        self.btn_remove_filter.setEnabled(has_selection)
        self.btn_move_filter_up.setEnabled(has_selection)
        self.btn_move_filter_down.setEnabled(has_selection)

    def on_remove_filter_clicked(self) -> None:
        row = self.lst_filters.currentIndex().row()
        self.filters_model.remove_filter(row)

    def on_move_filter_up_clicked(self) -> None:
        row = self.lst_filters.currentIndex().row()
        self.filters_model.move_filter(row, -1)
        self.lst_filters.setCurrentIndex(self.filters_model.index(row - 1))

    def on_move_filter_down_clicked(self) -> None:
        row = self.lst_filters.currentIndex().row()
        self.filters_model.move_filter(row, 1)
        self.lst_filters.setCurrentIndex(self.filters_model.index(row + 1))

    def on_filter_detail_changed(self) -> None:
        """Recreate and replace the selected filter when any detail widget changes."""
        current = self.lst_filters.currentIndex()
        if not current.isValid():
            return

        layer = self.cmb_filter_layer.currentLayer()
        field_name = self.cmb_filter_field.currentField()
        filter_type = self.cmb_filter_type.currentData()
        filter_name = self.edit_filter_title.text().strip()

        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            return
        if not field_name:
            return
        if not filter_name:
            return

        self.filters_model.replace_filter(
            current.row(),
            FieldFilter(
                layer=layer,
                field_name=field_name,
                filter_type=filter_type,
                filter_name=filter_name,
            ),
        )

    def on_filter_layer_fields_changed(self) -> None:
        """
        Update the fields in the filter field combo box based on the selected layer.
        """
        layer = self.cmb_filter_layer.currentLayer()
        self.cmb_filter_field.setLayer(layer)
        filter_type = self.cmb_filter_type.currentData()
        if filter_type in (FieldFilterType.SINGLE_SELECT, FieldFilterType.MULTI_SELECT):
            self.cmb_filter_field.setFilters(QgsFieldProxyModel.Filter.AllTypes)
        elif filter_type == FieldFilterType.CHECKBOX:
            self.cmb_filter_field.setFilters(QgsFieldProxyModel.Filter.Boolean)
        elif filter_type == FieldFilterType.DATE:
            self.cmb_filter_field.setFilters(QgsFieldProxyModel.Filter.Date)
        elif filter_type in (FieldFilterType.NUMBER, FieldFilterType.TEXT):
            self.cmb_filter_field.setFilters(
                QgsFieldProxyModel.Filter(QgsFieldProxyModel.Filter.Numeric | QgsFieldProxyModel.Filter.String)
            )

    def add_unnamed_filter(self, field_filter_type: FieldFilterType) -> None:
        """Create a default field filter with specific type and then select it in the list view to allow user to edit it right away."""
        self.filters_model.add_filter(
            FieldFilter(layer=None, field_name="", filter_type=field_filter_type, filter_name="Unnamed Filter")
        )
        self.lst_filters.setCurrentIndex(self.filters_model.index(self.filters_model.rowCount() - 1))
