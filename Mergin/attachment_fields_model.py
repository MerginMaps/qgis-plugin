from qgis.PyQt.QtGui import QStandardItemModel, QStandardItem
from qgis.PyQt.QtCore import Qt, QSize
from qgis.core import QgsProject, QgsMapLayer, QgsSymbolLayerUtils, QgsIconUtils


class AttachmentFieldsModel(QStandardItemModel):
    LAYER_ID = Qt.UserRole + 1
    FIELD_NAME = Qt.UserRole + 2
    EXPRESSION = Qt.UserRole + 3

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setHorizontalHeaderLabels(["Layer", "Field"])

        parent_item = self.invisibleRootItem()

        layers = QgsProject.instance().mapLayers()
        for layer_id, layer in layers.items():
            if layer.type() != QgsMapLayer.VectorLayer:
                continue

            for field in layer.fields():
                widget_setup = field.editorWidgetSetup()
                if widget_setup.type() != "ExternalResource":
                    continue

                if not widget_setup.config().get("DocumentViewer", 1):
                    continue

                item_layer = QStandardItem(f"{layer.name()}")
                if layer.renderer().type() == "singleSymbol":
                    icon = QgsSymbolLayerUtils.symbolPreviewIcon(layer.renderer().symbol(), QSize(16, 16))
                    item_layer.setIcon(icon)
                else:
                    item_layer.setIcon(QgsIconUtils.iconForLayer(layer))

                item_field = QStandardItem(f"{field.name()}")
                item_field.setData(layer_id, AttachmentFieldsModel.LAYER_ID)
                item_field.setData(field.name(), AttachmentFieldsModel.FIELD_NAME)
                exp, ok = QgsProject.instance().readEntry("Mergin", f"PhotoNaming/{layer_id}/{field.name()}")
                item_field.setData(exp, AttachmentFieldsModel.EXPRESSION)
                parent_item.appendRow([item_layer, item_field])
