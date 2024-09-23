import os

from qgis.PyQt import uic, QtCore
from qgis.PyQt.QtWidgets import QDialog, QAction
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel, QIcon
from qgis.PyQt.QtCore import QStringListModel, Qt
from qgis.utils import iface
from qgis.core import (
    QgsMessageLog,
    QgsApplication,
    QgsFeatureRequest,
    QgsVectorLayerCache
)
from qgis.gui import QgsGui, QgsMapToolPan, QgsAttributeTableModel, QgsAttributeTableFilterModel


from .utils import is_versioned_file, icon_path, format_datetime
from .mergin.utils import bytes_to_human_size

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_draft_versions_viewer.ui")


class VersionViewerDialog(QDialog):
    def __init__(self, parent=None):
        
        QDialog.__init__(self, parent)
        self.ui = uic.loadUi(ui_file, self)

        self.history_model = QStandardItemModel()

        # self.history_model.setHeaderData(0, Qt.Horizontal, "Versions", Qt.DisplayRole)
        self.history_model.setHorizontalHeaderItem(0, QStandardItem("Versions"))

        self.history_treeview.setModel(self.history_model)
        
        root_node = self.history_model.invisibleRootItem()
        date_1 = QStandardItem("September 16")

        item = QStandardItem("v25  ValentinB")

        date_1.appendRow(QStandardItem("v25  ValentinB"))
        date_1.appendRow(QStandardItem("v24  ValentinB"))
        date_1.appendRow(QStandardItem("v23  ValentinB"))


        date_2 = QStandardItem("September 17")
        date_2.appendRow(QStandardItem("v22  ValentinB"))
        date_2.appendRow(QStandardItem("v21  ValentinB"))

        root_node.appendRow(date_1)
        root_node.appendRow(date_2)

        self.history_treeview.expandRecursively(root_node.index())

        model = QStringListModel()
        model.setStringList(["Line example", "New_scratch_layer"])
        self.layer_list.setModel(model)

        height = 30
        self.toolbar.setMinimumHeight(height)
        self.temporal_control.setMinimumHeight(height)
        # self.verticalSpacer_3.setMinimumHeight(100)
        self.verticalLayout.insertSpacing(0,height)

        self.map_canvas.setDisabled(False)
        self.map_canvas.setEnabled(False)

        # self.toolbar.
        self.zoom_full_action = QAction(
            QgsApplication.getThemeIcon("/mActionZoomFullExtent.svg"), "Zoom Full", self
        )
        self.toolbar.addAction(self.zoom_full_action)

        self.zoom_selected_action = QAction(
            QgsApplication.getThemeIcon("/mActionZoomToSelected.svg"), "Zoom To Selection", self
        )
        self.toolbar.addAction(self.zoom_selected_action)

        height = max(
                    [self.map_canvas.minimumSizeHint().height(), self.attribute_table.minimumSizeHint().height()]
                )
        self.splitter.setSizes([height, height])


        layers = iface.mapCanvas().layers()
        self.map_canvas.setLayers(layers)

        self.layer_cache = QgsVectorLayerCache(layers[0], 1000)
        self.layer_cache.setCacheGeometry(False)

        self.table_model = QgsAttributeTableModel(self.layer_cache)
        self.table_model.setRequest(QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry).setLimit(100))

        self.filter_model = QgsAttributeTableFilterModel(self.map_canvas, self.table_model)

        self.attribute_table.setModel(self.filter_model)
        self.table_model.loadLayer()
        
        self.map_canvas.setDestinationCrs(layers[0].crs())
        extent = layers[0].extent()
        d = min(extent.width(), extent.height())
        if d == 0:
            d = 1
        extent = extent.buffered(d * 0.07)
        self.map_canvas.setExtent(extent)



        # self.history_verticalLayout.hide()
        self.splitter_2.setSizes([50,50, 200])
        self.splitter_2.setCollapsible(0, True)

        # self.tabWidget.tabBar().setDocumentMode(True)
        # self.tabWidget.tabBar().setExpanding(False)
        
        # self.splitter_2.setStretchFactor(0, 0)
        
        # self.attribute_table_2.hide()

        self.version_details = {
                "author": "ValentinB_lutraconsulting",
                "changes": {
                    "added": [],
                    "removed": [],
                    "updated": [
                    {
                        "change": "updated",
                        "checksum": "5c9cdf250e6fbfe37c55dbb6dc299ce5db697136",
                        "diff": {
                        "checksum": "d42ac00c1ac157bab94e0627d104d49767c98d63",
                        "path": "line example.gpkg-diff-d58ebf64-15d7-4847-840d-2dec44a6c987",
                        "size": 129
                        },
                        "expiration": "2024-09-08T14:35:04Z",
                        "mtime": "2024-09-06T14:35:07Z",
                        "path": "line example.gpkg",
                        "size": 98304
                    },
                    {
                        "change": "updated",
                        "checksum": "3e833120cc04d3bc88a3c38bb14b58dea3e3e9d2",
                        "diff": {
                        "checksum": "7b86f60f3665982c03e39a1c3a186ff64fba8439",
                        "path": "New_scratch_layer.gpkg-diff-01ffb906-086b-4980-b205-6c50284e8ac5",
                        "size": 291
                        },
                        "expiration": "2024-09-08T14:35:07Z",
                        "mtime": "2024-09-06T14:35:07Z",
                        "path": "New_scratch_layer.gpkg",
                        "size": 98304
                    }
                    ]
                },
                "changesets": {
                    "New_scratch_layer.gpkg": {
                    "size": 291,
                    "summary": [
                        {
                        "delete": 1,
                        "insert": 1,
                        "table": "New_scratch_layer",
                        "update": 0
                        }
                    ]
                    },
                    "line example.gpkg": {
                    "size": 129,
                    "summary": [
                        {
                        "delete": 0,
                        "insert": 1,
                        "table": "line example",
                        "update": 0
                        }
                    ]
                    }
                },
                "created": "2024-09-06T14:35:07Z",
                "name": "v21",
                "namespace": "solar panel workspace cop",
                "project_name": "terrain_poi2",
                "project_size": 4533043,
                "user_agent": "Input/2024.3.1 (android/13.0)"
                }

        self.icons = {
            "added": "plus.svg",
            "removed": "trash.svg",
            "updated": "pencil.svg",
            "renamed": "pencil.svg",
            "table": "table.svg",
        }
        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["Details"])
        self.details_treeview.setModel(self.model)
        self.populate_details()
        self.details_treeview.expandAll()

    def populate_details(self):
        self.edit_project_size.setText(bytes_to_human_size(self.version_details["project_size"]))
        self.edit_created.setText(format_datetime(self.version_details["created"]))
        self.edit_user_agent.setText(self.version_details["user_agent"])

        root_item = QStandardItem(f"Changes in version {self.version_details['name']}")
        self.model.appendRow(root_item)
        for category in self.version_details["changes"]:
            for item in self.version_details["changes"][category]:
                path = item["path"]
                item = self._get_icon_item(category, path)
                if is_versioned_file(path):
                    if path in self.version_details["changesets"]:
                        for sub_item in self._versioned_file_summary_items(
                            self.version_details["changesets"][path]["summary"]
                        ):
                            item.appendRow(sub_item)
                root_item.appendRow(item)

    def _get_icon_item(self, key, text):
        path = icon_path(self.icons[key])
        item = QStandardItem(text)
        item.setIcon(QIcon(path))
        return item

    def _versioned_file_summary_items(self, summary):
        items = []
        for s in summary:
            table_name_item = self._get_icon_item("table", s["table"])
            for row in self._table_summary_items(s):
                table_name_item.appendRow(row)
            items.append(table_name_item)

        return items

    def _table_summary_items(self, summary):
        return [QStandardItem("{}: {}".format(k, summary[k])) for k in summary if k != "table"]


        
    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_C:          
            # QgsMessageLog.logMessage("blabla")
            if self.stackedWidget.currentIndex() == 0:
                self.stackedWidget.setCurrentIndex(1)
                self.tabWidget.setCurrentIndex(1)
            else:
                self.stackedWidget.setCurrentIndex(0)
                self.tabWidget.setCurrentIndex(0)

            return

