import os

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QDialog

from qgis.core import QgsProject, QgsMapLayerProxyModel, QgsVectorLayerCache, QgsFeatureRequest
from qgis.gui import QgsMapToolPan, QgsAttributeTableModel, QgsAttributeTableFilterModel
from qgis.utils import iface

from .mergin.merginproject import MerginProject

from .diff import make_local_changes_layer

from .utils import icon_path

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'ui', 'ui_diff_viewer_dialog.ui')


class DiffViewerDialog(QDialog):

    def __init__(self, parent=None):
        QDialog.__init__(self, parent)
        self.ui = uic.loadUi(ui_file, self)

        self.map_canvas.enableAntiAliasing(True)
        self.pan_tool = QgsMapToolPan(self.map_canvas)
        self.map_canvas.setMapTool(self.pan_tool)

        self.diff_layer_cbo.setAllowEmptyLayer(True)
        self.diff_layer_cbo.setFilters(QgsMapLayerProxyModel.HasGeometry)
        self.diff_layer_cbo.setCurrentIndex(-1)
        self.diff_layer_cbo.layerChanged.connect(self.diff_layer_changed)

        self.add_to_project_btn.setIcon(QIcon(icon_path('file-plus.svg')))
        self.add_to_project_btn.clicked.connect(self.add_diff_to_project)

        self.project_layers_checkbox.stateChanged.connect(self.toggle_project_layers)

        self.diff_layer = None
        self.filter_model = None

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

        if self.diff_layer:
            layers.insert(0, self.diff_layer)

        return layers

    def diff_layer_changed(self, layer):
        base_layer = self.diff_layer_cbo.currentLayer()
        if base_layer is not None:
            mp = MerginProject(QgsProject.instance().homePath())
            self.diff_layer, msg = make_local_changes_layer(mp, base_layer)
            config = self.diff_layer.attributeTableConfig()

            layer_cache = QgsVectorLayerCache(self.diff_layer, 1000, self)
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
        else:
            self.diff_layer = None

        layers = self.collect_layers(self.project_layers_checkbox.checkState())
        self.update_canvas(layers)

    def add_diff_to_project(self):
        if self.diff_layer:
            QgsProject.instance().addMapLayer(self.diff_layer)
