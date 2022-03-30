import os

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QStyle,
    QSizePolicy,
    QPushButton
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QStandardItemModel, QStandardItem, QIcon

from qgis.gui import QgsGui
from qgis.core import QgsApplication, QgsProject
from .utils import is_versioned_file

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'ui', 'ui_status_dialog.ui')


class ProjectStatusDialog(QDialog):

    icons = {
        "added": "images/FA_icons/plus.svg",
        "removed": "images/FA_icons/trash.svg",
        "updated": "images/FA_icons/edit.svg",
        "renamed": "images/FA_icons/edit.svg",
        "table": "images/FA_icons/table.svg",
    }

    def __init__(
        self, pull_changes, push_changes, push_changes_summary, has_write_permissions, validation_results,
            mergin_project=None, parent=None, show_sync_button=False
    ):
        QDialog.__init__(self, parent)
        self.ui = uic.loadUi(ui_file, self)

        QgsGui.instance().enableAutoGeometryRestore(self)

        if show_sync_button:
            self.btn_sync = QPushButton("Sync")
            self.btn_sync.clicked.connect(self.sync_project)
            self.ui.buttonBox.addButton(self.btn_sync, QDialogButtonBox.ActionRole)

        self.validation_results = validation_results
        self.mp = mergin_project

        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["Status"])
        self.treeStatus.setModel(self.model)

        self.check_any_changes(pull_changes, push_changes)
        self.add_content(pull_changes, "Server changes", True)
        self.add_content(push_changes, "Local changes", False, push_changes_summary)
        self.treeStatus.expandAll()

        if not self.validation_results:
            self.ui.lblWarnings.hide()
            self.ui.txtWarnings.hide()
        else:
            self.show_validation_results()

        has_files_to_replace = any(
            ["diff" not in file and is_versioned_file(file["path"]) for file in push_changes["updated"]]
        )
        info_text = self._get_info_text(has_files_to_replace, has_write_permissions, self.mp.has_unfinished_pull())
        for msg in info_text:
            self.ui.messageBar.pushWarning("WARNING", msg)

    def _get_info_text(self, has_files_to_replace, has_write_permissions, has_unfinished_pull):
        msg = []
        if not has_write_permissions:
            msg.append(f"You don't have writing permissions to this project. Changes won't be synced!")

        if has_files_to_replace:
            msg.append(
                f"Unable to compare some of the modified files with their server version - "
                f"their history will be lost if uploaded."
            )

        if has_unfinished_pull:
            msg.append(
                f"The previous pull has not finished completely: status "
                f"of some files may be reported incorrectly."
            )

        return msg

    def check_any_changes(self, pull_changes, push_changes):
        if not sum(len(v) for v in list(pull_changes.values()) + list(push_changes.values())):
            root_item = QStandardItem("No changes")
            self.model.appendRow(root_item)

    def add_content(self, changes, root_text, is_server, changes_summary={}):
        """
        Adds rows with changes info
        :param changes: Dict of added/removed/updated/renamed changes
        :param root_text: Text for the root item
        :param is_server: True if changes are related to server file changes
        :param changes_summary: If given and non empty, extra rows are added from geodiff summary.
        :return:
        """
        if all(not changes[k] for k in changes):
            return

        root_item = QStandardItem(root_text)
        self.model.appendRow(root_item)
        for category in changes:
            for file in changes[category]:
                path = file["path"]
                item = self._get_icon_item(category, path)
                if is_versioned_file(path):
                    if path in changes_summary:
                        for sub_item in self._versioned_file_summary_items(changes_summary[path]["geodiff_summary"]):
                            item.appendRow(sub_item)
                    elif not is_server and category != "added":
                        item.appendRow(QStandardItem("Unable to detect changes"))
                        msg = f"Mergin plugin: Unable to detect changes for {path}"
                        QgsApplication.messageLog().logMessage(msg)
                        if self.mp is not None:
                            self.mp.log.warning(msg)
                root_item.appendRow(item)

    def _versioned_file_summary_items(self, geodiff_summary):
        items = []
        for s in geodiff_summary:
            table_name_item = self._get_icon_item("table", s["table"])
            for row in self._table_summary_items(s):
                table_name_item.appendRow(row)
            items.append(table_name_item)

        return items

    def _table_summary_items(self, summary):
        return [QStandardItem("{}: {}".format(k, summary[k])) for k in summary if k != "table"]

    def _get_icon_item(self, key, text):
        path = os.path.join(os.path.dirname(os.path.realpath(__file__)), self.icons[key])
        item = QStandardItem(text)
        item.setIcon(QIcon(path))
        return item

    def show_validation_results(self):
        html = []
        map_layers = QgsProject.instance().mapLayers()
        for issues_data in sorted(self.validation_results):
            level, issue = issues_data
            layer_ids = self.validation_results[issues_data]
            html.append(f"<h3>{issue}</h3>")
            items = []
            for lid in sorted(layer_ids, key=lambda x: map_layers[x].name()):
                layer = map_layers[lid]
                items.append(f"<li>{layer.name()}</li>")
            html.append(f"<ul>{''.join(items)}</ul>")

        self.txtWarnings.setHtml(''.join(html))

    def sync_project(self):
        pass
