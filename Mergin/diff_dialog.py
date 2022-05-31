import os

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtWidgets import (
    QDialog,
    QPushButton,
    QDialogButtonBox,
    QMenu
)
from qgis.core import (
    QgsProject,
    QgsVectorLayerCache,
    QgsFeatureRequest,
    QgsIconUtils,
    QgsMapLayer,
    QgsMessageLog,
    Qgis
)
from qgis.gui import (
    QgsGui,
    QgsMapToolPan,
    QgsAttributeTableModel,
    QgsAttributeTableFilterModel
)
from qgis.utils import iface, OverrideCursor

from .mergin.merginproject import MerginProject
from .diff import make_local_changes_layer
from .utils import icon_path

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'ui', 'ui_diff_viewer_dialog.ui')


class DiffViewerDialog(QDialog):

    def __init__(self, parent=None):
        QDialog.__init__(self, parent)
        self.ui = uic.loadUi(ui_file, self)

        with OverrideCursor(Qt.WaitCursor):
            QgsGui.instance().enableAutoGeometryRestore(self)
            settings = QSettings()
            state = settings.value("Mergin/changesViewerSplitterSize")
            if state:
                self.splitter.restoreState(state)

            btn_add_changes = QPushButton("Add to project")
            btn_add_changes.setIcon(QIcon(icon_path('file-plus.svg')))
            self.ui.buttonBox.addButton(btn_add_changes, QDialogButtonBox.ActionRole)
            menu = QMenu()
            add_current_action = menu.addAction(QIcon(icon_path('file-plus.svg')), "Add current changes layer to project")
            add_current_action.triggered.connect(self.add_current_to_project)
            add_all_action = menu.addAction(QIcon(icon_path('folder-plus.svg')), "Add all changes layers to project")
            add_all_action.triggered.connect(self.add_all_to_project)
            btn_add_changes.setMenu(menu)

            self.project_layers_checkbox.stateChanged.connect(self.toggle_project_layers)

            self.map_canvas.enableAntiAliasing(True)
            self.map_canvas.setSelectionColor(QColor(Qt.cyan))
            self.pan_tool = QgsMapToolPan(self.map_canvas)
            self.map_canvas.setMapTool(self.pan_tool)

            self.tab_bar.setUsesScrollButtons(True)
            self.tab_bar.currentChanged.connect(self.diff_layer_changed)

            self.current_diff = None
            self.diff_layers = []
            self.filter_model = None

            self.create_tabs()

    def reject(self):
        self.saveSplitterState()
        QDialog.reject(self)

    def closeEvent(self, event):
        self.saveSplitterState()
        QDialog.closeEvent(self, event)

    def saveSplitterState(self):
        settings = QSettings()
        settings.setValue("Mergin/changesViewerSplitterSize", self.splitter.saveState())

    def create_tabs(self):
        mp = MerginProject(QgsProject.instance().homePath())
        project_layers = QgsProject.instance().mapLayers()
        for layer in project_layers.values():
            if layer.type() != QgsMapLayer.VectorLayer:
                continue

            if layer.dataProvider().storageType() != "GPKG":
                QgsMessageLog.logMessage(f"Layer {layer.name()} is not supported.", "Mergin")
                continue

            vl, msg = make_local_changes_layer(mp, layer)
            if vl is None:
                QgsMessageLog.logMessage(msg, "Mergin")
                continue

            self.diff_layers.append(vl)
            self.tab_bar.addTab(QgsIconUtils.iconForLayer(vl), vl.name())
        self.tab_bar.setCurrentIndex(0)

    def toggle_project_layers(self, state):
        layers = self.collect_layers(state)
        self.update_canvas(layers)

    def update_canvas(self, layers):
        self.map_canvas.setLayers(layers)
        if layers:
            self.map_canvas.setDestinationCrs(layers[0].crs())
            extent = layers[0].extent()
            d = min(extent.width(), extent.height())
            if d == 0:
                d = 1
            extent = extent.buffered(d * 0.07)
            self.map_canvas.setExtent(extent)
        self.map_canvas.refresh()

    def collect_layers(self, state):
        if state == Qt.Checked:
            layers = iface.mapCanvas().layers()
        else:
            layers = []

        if self.current_diff:
            layers.insert(0, self.current_diff)

        return layers

    def diff_layer_changed(self, index):
        if index > len(self.diff_layers):
            return

        self.current_diff = self.diff_layers[index]
        config = self.current_diff.attributeTableConfig()

        layer_cache = QgsVectorLayerCache(self.current_diff, 1000, self)
        layer_cache.setCacheGeometry(False)
        table_model = QgsAttributeTableModel(layer_cache, self)
        self.filter_model = QgsAttributeTableFilterModel(None, table_model, self)
        table_model.setRequest(QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry).setLimit(100))
        layer_cache.setParent(table_model)
        table_model.setParent(self.filter_model)
        self.attribute_table.setModel(self.filter_model)
        table_model.loadLayer()
        self.filter_model.setAttributeTableConfig(config)
        self.attribute_table.setAttributeTableConfig(config)

        layers = self.collect_layers(self.project_layers_checkbox.checkState())
        self.update_canvas(layers)

    def add_current_to_project(self):
        if self.current_diff:
            QgsProject.instance().addMapLayer(self.current_diff)

    def add_all_to_project(self):
        for layer in self.diff_layers:
            QgsProject.instance().addMapLayer(layer)
