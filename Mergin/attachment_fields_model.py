from qgis.PyQt.QtGui import QStandardItemModel, QStandardItem
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsMapLayer


class AttachmentFieldsModel(QStandardItemModel):

    LAYER_ID = Qt.UserRole + 1
    FIELD_NAME = Qt.UserRole + 2
    EXPRESSION = Qt.UserRole + 3

    def __init__(self, parent=None):
        super().__init__(parent)

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

                item = QStandardItem(f"{layer.name()} - {field.name()}")
                item.setData(layer_id, AttachmentFieldsModel.LAYER_ID)
                item.setData(field.name(), AttachmentFieldsModel.FIELD_NAME)
                exp, ok = QgsProject.instance().readEntry("Mergin", f"PhotoNaming/{layer_id}/{field.name()}")
                item.setData(exp, AttachmentFieldsModel.EXPRESSION)
                self.appendRow(item)
