import os

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog
from qgis.PyQt.QtGui import QStandardItemModel, QStandardItem, QIcon

from qgis.gui import QgsGui

from .utils import is_versioned_file, icon_path, format_size, format_datetime

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "ui_version_details_dialog.ui")


class VersionDetailsDialog(QDialog):
    icons = {
        "added": "plus.svg",
        "removed": "trash.svg",
        "updated": "pencil.svg",
        "renamed": "pencil.svg",
        "table": "table.svg",
    }

    def __init__(self, version_details, parent=None):
        QDialog.__init__(self, parent)
        self.ui = uic.loadUi(ui_file, self)
        QgsGui.instance().enableAutoGeometryRestore(self)

        self.version_details = version_details

        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["Details"])
        self.tree_details.setModel(self.model)
        self.populate_details()
        self.tree_details.expandAll()

    def populate_details(self):
        self.edit_version.setText(self.version_details["name"])
        self.edit_author.setText(self.version_details["author"])
        self.edit_project_size.setText(format_size(self.version_details["project_size"]))
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
