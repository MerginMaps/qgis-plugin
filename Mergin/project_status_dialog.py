import os
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTabWidget,
    QTreeView,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QStyle,
    QSizePolicy
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QIcon
from qgis.core import QgsApplication, QgsProject
from .utils import is_versioned_file


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
            mergin_project=None, parent=None
    ):
        super(ProjectStatusDialog, self).__init__(parent)
        self.validation_results = validation_results
        self.setWindowTitle("Project status")
        self.table = QTreeView()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["Status"])
        self.table.setModel(self.model)
        self.mp = mergin_project

        self.check_any_changes(pull_changes, push_changes)
        self.add_content(pull_changes, "Server changes", True)
        self.add_content(push_changes, "Local changes", False, push_changes_summary)
        self.table.expandAll()

        main_lout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        main_lout.addWidget(self.tabs)
        self.status_tab = QWidget()
        self.valid_tab = QWidget()
        self.tabs.addTab(self.status_tab, "Status")
        self.tabs.addTab(self.valid_tab, "Validation results")

        status_lay = QVBoxLayout(self.status_tab)
        if self.mp.has_unfinished_pull():
            warn_lay = QHBoxLayout()
            lbl_warn_icon = QLabel()
            lbl_warn_icon.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            icon = self.style().standardIcon(QStyle.SP_MessageBoxWarning)
            lbl_warn_icon.setPixmap(icon.pixmap(icon.availableSizes()[0]))
            warn_lay.addWidget(lbl_warn_icon)
            lbl_unfinished = QLabel()
            lbl_unfinished.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            lbl_unfinished.setWordWrap(True)
            lbl_unfinished.setText(
                "The previous pull has not finished completely: status "
                "of some files may be reported incorrectly."
            )
            warn_lay.addWidget(lbl_unfinished)
            status_lay.addLayout(warn_lay)

        status_lay.addWidget(self.table)
        has_files_to_replace = any(
            ["diff" not in file and is_versioned_file(file["path"]) for file in push_changes["updated"]]
        )
        info_text = self._get_info_text(has_files_to_replace, has_write_permissions)
        if info_text:
            text_box = QLabel()
            text_box.setWordWrap(True)
            text_box.setText(info_text)
            status_lay.addWidget(text_box)

        box = QDialogButtonBox(QDialogButtonBox.Ok, centerButtons=True,)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        main_lout.addWidget(box, Qt.AlignCenter)

        self.valid_view = QTreeView()
        self.valid_view.setStyleSheet("QTreeView::item { padding: 5px }")
        self.valid_model = QStandardItemModel()
        self.show_validation_results()

        self.resize(640, 640)

    def _get_info_text(self, has_files_to_replace, has_write_permissions):
        msg = ""
        if not has_write_permissions:
            msg += f"WARNING: You don't have writing permissions to this project. Changes won't be synced!\n"

        if has_files_to_replace:
            msg += (
                f"\nWARNING: Unable to compare some of the modified files with their server version - "
                f"their history will be lost if uploaded."
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
        lout = QVBoxLayout(self.valid_tab)
        lout.addWidget(self.valid_view)
        self.valid_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.valid_model.setHorizontalHeaderLabels(["Validation results"])
        self.valid_view.setModel(self.valid_model)

        map_layers = QgsProject.instance().mapLayers()
        for issues_data in sorted(self.validation_results):
            level, issue = issues_data
            layer_ids = self.validation_results[issues_data]
            issue_item = QStandardItem(issue)
            for lid in sorted(layer_ids, key=lambda x: map_layers[x].name()):
                layer = map_layers[lid]
                lyr_item = QStandardItem(f"- {layer.name()}")
                lyr_item.setToolTip(layer.publicSource())
                issue_item.appendRow(lyr_item)
            self.valid_model.appendRow(issue_item)

        self.valid_view.expandAll()
