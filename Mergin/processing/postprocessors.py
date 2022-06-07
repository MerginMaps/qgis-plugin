from qgis.core import QgsProcessingLayerPostProcessorInterface

from ..diff import style_diff_layer


class StylingPostProcessor(QgsProcessingLayerPostProcessorInterface):
    instance = None

    def __init__(self, table_schema):
        super().__init__()
        self.table_schema = table_schema

    def postProcessLayer(self, layer, context, feedback):
        style_diff_layer(layer, self.table_schema)
        layer.triggerRepaint()

    # Hack to work around sip bug!
    @staticmethod
    def create(table_schema):
        StylingPostProcessor.instance = StylingPostProcessor(table_schema)
        return StylingPostProcessor.instance
