# GPLv3 license
# Copyright Lutra Consulting Limited

import json
import os
import typing
from qgis.PyQt import uic
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox
from qgis.core import (
    QgsProject,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeature,
    QgsFeatureRequest,
    QgsExpression,
    QgsMapLayer,
    QgsCoordinateReferenceSystem,
)
from qgis.gui import (
    QgsOptionsWidgetFactory,
    QgsOptionsPageWidget,
    QgsColorButton,
    QgsProjectionSelectionWidget,
    QgsCoordinateReferenceSystemProxyModel,
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
    get_missing_geoid_grids,
    download_grids_task,
    existing_grid_files_for_crs,
    project_defined_transformation,
    _grids_from_proj_string,
    _grid_available_in_project,
    _get_operations,
    grid_details_for_names,
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

        # Vertical CRS
        self.cmb_vertical_crs.setFilters(QgsCoordinateReferenceSystemProxyModel.FilterVertical)
        self.cmb_vertical_crs.setOptionVisible(QgsProjectionSelectionWidget.CurrentCrs, False)
        self.cmb_vertical_crs.setDialogTitle("Target Vertical CRS")
        self.label_vcrs_warning.setVisible(False)
        self.label_vcrs_warning.setOpenExternalLinks(False)
        self.label_vcrs_warning.linkActivated.connect(self._download_geoid_grid)

        QgsProject.instance().transformContextChanged.connect(
            lambda: self._check_geoid_grid(self.cmb_vertical_crs.crs())
        )

        use_vcrs, ok = QgsProject.instance().readBoolEntry("Mergin", "ElevationTransformationEnabled", False)
        self.chk_use_vertical_crs.setChecked(use_vcrs)
        self.cmb_vertical_crs.setEnabled(use_vcrs)

        vcrs_wkt, ok = QgsProject.instance().readEntry("Mergin", "TargetVerticalCRS")
        if ok and vcrs_wkt:
            crs = QgsCoordinateReferenceSystem.fromWkt(vcrs_wkt)
            if crs.isValid():
                self.cmb_vertical_crs.setCrs(crs)

        self._pending_grids = []
        self.chk_use_vertical_crs.stateChanged.connect(self._vcrs_checkbox_changed)
        self.cmb_vertical_crs.crsChanged.connect(self._check_geoid_grid)

        # run initial grid check if already enabled
        if use_vcrs and vcrs_wkt:
            self._check_geoid_grid(self.cmb_vertical_crs.crs())

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

    def _vcrs_checkbox_changed(self, state):
        enabled = self.chk_use_vertical_crs.isChecked()
        self.cmb_vertical_crs.setEnabled(enabled)
        if enabled:
            self._check_geoid_grid(self.cmb_vertical_crs.crs())
        else:
            self.label_vcrs_warning.setVisible(False)

    def _check_geoid_grid(self, crs: QgsCoordinateReferenceSystem):
        """
        Evaluates the selected vertical CRS to determine if a PROJ transformation grid
        is required for accurate elevation calculation in the mobile app.

        If the project has a datum transformation defined between EPSG:4979 and the CRS,
        that specific transform is used to determine grid requirements. Otherwise the
        standard PROJ operation list is consulted. When multiple operations exist and no
        project-level transform is configured the user is warned to set one up.
        """
        self.label_vcrs_warning.setVisible(False)
        self._pending_grids = []
        if not crs.isValid() or not self.chk_use_vertical_crs.isChecked():
            return

        # Check if the project has an explicit datum transformation configured.
        has_transform, transform_str = project_defined_transformation(crs)

        if has_transform:
            # Derive grid requirements solely from the project-defined transform string.
            grids = _grids_from_proj_string(transform_str)
            if not grids:
                # Transform does not require any grid file.
                self.label_vcrs_warning.setVisible(False)
                return

            project_dir = self.local_project_dir or ""
            available = [g for g in grids if _grid_available_in_project(project_dir, g.shortName)]

            if available:
                text = f'<font color="green">Using grid {available[0].shortName} \u2713.</font>'
                if len(available) > 1:
                    text += (
                        f'<font color="red"> Also found other relevant grids: '
                        f'{", ".join(g.shortName for g in available[1:])}. '
                        f"You should only have one relevant grid for conversion.</font>"
                    )
                self.label_vcrs_warning.setText(text)
                self.label_vcrs_warning.setVisible(True)
                return

            else:
                self._pending_grids = grid_details_for_names(set(g.shortName for g in grids), crs)
                names = ", ".join(g.shortName for g in grids)
                self.label_vcrs_warning.setText(
                    f'<font color="red">The selected vertical CRS requires the following geoid grid '
                    f"in order to work properly \u2013 {names}. "
                    f'<a href="download"><font color="red">Click here</font></a> to automatically '
                    f"download it and add to your project.</font>"
                )
                self.label_vcrs_warning.setVisible(True)
                return

        # No project-defined transformation – use the standard process.
        operations = _get_operations(crs)

        # Warn when multiple operations are available so the user knows to pick one in transformations
        multi_op_warning = ""
        if len(operations) > 1:
            multi_op_warning = (
                '<font color="orange">Multiple coordinate operations are available for this CRS. '
                "Please configure the datum transformation on the project level "
                "(Project \u2192 Properties \u2192 Transformations) "
                "to ensure the correct operation is used.</font>"
            )
            self.label_vcrs_warning.setText(multi_op_warning)
            self.label_vcrs_warning.setVisible(True)
            return

        existing_grids = existing_grid_files_for_crs(self.local_project_dir, crs)

        if existing_grids:
            text = f'<font color="green">Using grid {existing_grids[0]} \u2713.</font>'
            self.label_vcrs_warning.setText(text)
            self.label_vcrs_warning.setVisible(True)
            return

        grid_status = get_missing_geoid_grids(crs, self.local_project_dir)

        # no grid required according to PROJ
        if grid_status["ballpark"]:
            if multi_op_warning:
                self.label_vcrs_warning.setText(multi_op_warning.strip())
                self.label_vcrs_warning.setVisible(True)
            else:
                self.label_vcrs_warning.setVisible(False)
            return

        missing = grid_status["missing"]
        if not missing:
            if multi_op_warning:
                self.label_vcrs_warning.setText(multi_op_warning.strip())
                self.label_vcrs_warning.setVisible(True)
            else:
                self.label_vcrs_warning.setVisible(False)
            return

        self._pending_grids = missing
        names = ", ".join(g.shortName for g in missing)
        self.label_vcrs_warning.setText(
            f'<font color="red">The selected vertical CRS requires the following geoid grid(s) '
            f"in order to work properly \u2013 {names}. "
            f'<a href="download"><font color="red">Click here</font></a> to automatically '
            f"download it and add to your project.</font>" + multi_op_warning
        )
        self.label_vcrs_warning.setVisible(True)

    def _download_geoid_grid(self, link: str):
        """
        Triggered when the user clicks the download link in the missing grid warning label.

        Initiates a background QgsTask to download the required PROJ grids
        from the official CDN directly into the project's 'proj/' directory.

        :param link: The href string of the clicked HTML link.
        """
        if not self._pending_grids:
            return

        no_url = [g.shortName for g in self._pending_grids if not g.url]
        downloadable = [g for g in self._pending_grids if g.url]

        if no_url:
            QMessageBox.warning(
                self,
                "Cannot download automatically",
                "The following grid(s) have no download URL and must be installed manually "
                "via the QGIS Resource Manager or by installing a PROJ data package:\n\n" + ", ".join(no_url),
            )
            if not downloadable:
                return

        if not self.local_project_dir:
            urls = "\n".join(g.url for g in downloadable)
            QMessageBox.information(
                self,
                "Download geoid grid",
                f"Please download the geoid grid(s) manually and place them in your project's 'proj/' folder:\n{urls}",
            )
            return

        # start UI animation
        self._download_dot_count = 0

        def _tick():
            self._download_dot_count = (self._download_dot_count + 1) % 4
            dots = "." * self._download_dot_count
            self.label_vcrs_warning.setText(f'<font color="gray">Downloading geoid grid(s){dots}</font>')

        self._download_timer = QTimer(self)
        self._download_timer.timeout.connect(_tick)
        _tick()
        self._download_timer.start(400)

        # callbacks
        def on_success():
            self._download_timer.stop()
            self.label_vcrs_warning.setVisible(False)
            QMessageBox.information(self, "Download complete", "Geoid grid(s) downloaded and added to your project.")
            # re-trigger the check to update the UI state
            self._check_geoid_grid(self.cmb_vertical_crs.crs())

        def on_error(errors):
            self._download_timer.stop()
            QMessageBox.warning(self, "Download failed", "Could not download:\n" + "\n".join(errors))
            # re-trigger the check to reset the label text back
            self._check_geoid_grid(self.cmb_vertical_crs.crs())

        # fire the task
        dest_dir = os.path.join(self.local_project_dir, "proj")
        self._download_task = download_grids_task(downloadable, dest_dir, on_success, on_error)

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

        use_vcrs = self.chk_use_vertical_crs.isChecked()
        QgsProject.instance().writeEntry("Mergin", "ElevationTransformationEnabled", use_vcrs)
        if use_vcrs:
            crs = self.cmb_vertical_crs.crs()
            QgsProject.instance().writeEntry("Mergin", "TargetVerticalCRS", crs.toWkt() if crs.isValid() else "")
        else:
            QgsProject.instance().writeEntry("Mergin", "TargetVerticalCRS", "")

    def colors_change_state(self) -> None:
        """
        Enable/disable color buttons based on the state of the map sketches checkbox.
        """
        for i in range(self.mColorsHorizontalLayout.count()):
            item = self.mColorsHorizontalLayout.itemAt(i).widget()
            if isinstance(item, QgsColorButton):
                item.setEnabled(self.chk_map_sketches_enabled.isChecked())
