import os
from PyQt5.QtWidgets import QDialog, QLabel, QTableWidget, QHeaderView, QTableWidgetItem, \
    QDialogButtonBox, QVBoxLayout, QTreeView, QAbstractItemView
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QIcon

from .utils import is_versioned_file


class ProjectStatusDialog(QDialog):

    icons = {
        'added': 'images/FA_icons/plus.svg',
        'removed': 'images/FA_icons/trash.svg',
        'updated': 'images/FA_icons/edit.svg',
        'renamed': 'images/FA_icons/edit.svg',
        'table': 'images/FA_icons/table.svg'
    }

    def __init__(self, pull_changes, push_changes, push_changes_summary, has_write_permissions, parent=None):
        super(ProjectStatusDialog, self).__init__(parent)

        self.setWindowTitle("Project status")
        self.table = QTreeView()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["Status"])
        self.table.setModel(self.model)

        self.add_content(pull_changes, 'Server changes', True)
        self.add_content(push_changes, 'Local changes', False, push_changes_summary)
        self.table.expandAll()

        box = QDialogButtonBox(
            QDialogButtonBox.Ok,
            centerButtons=True,
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self.table)
        has_files_to_replace = any(
            ["diff" not in file and is_versioned_file(file['path']) for file in push_changes["updated"]])
        info_text = self._get_info_text(has_files_to_replace, has_write_permissions)
        if info_text:
            text_box = QLabel()
            text_box.setWordWrap(True)
            text_box.setText(info_text)
            lay.addWidget(text_box)
        lay.addWidget(box, Qt.AlignCenter)

        self.resize(640, 640)

    def _get_info_text(self, has_files_to_replace, has_write_permissions):
        msg = ""
        if not has_write_permissions:
            msg += f"WARNING: You don't have writing permissions to this project. Changes won't be synced!\n"

        if has_files_to_replace:
            msg += f"\nWARNING: Unable to compare some of the modified files with their server version - " \
                   f"their history will be lost if uploaded."
        return msg

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
                path = file['path']
                item = self._get_icon_item(category, path)
                if is_versioned_file(path):
                    if path in changes_summary:
                        for sub_item in self._versioned_file_summary_items(changes_summary[path]['geodiff_summary']):
                            item.appendRow(sub_item)
                    elif not is_server:
                        item.appendRow(QStandardItem("Unable to detect changes"))
                root_item.appendRow(item)

    def _versioned_file_summary_items(self, geodiff_summary):
        items = []
        for s in geodiff_summary:
            table_name_item = self._get_icon_item('table', s['table'])
            for row in self._table_summary_items(s):
                table_name_item.appendRow(row)
            items.append(table_name_item)

        return items

    def _table_summary_items(self, summary):
        return [QStandardItem("{}: {}".format(k, summary[k])) for k in summary if k!='table']

    def _get_icon_item(self, key, text):
        path = os.path.join(os.path.dirname(os.path.realpath(__file__)), self.icons[key])
        item = QStandardItem(text)
        item.setIcon(QIcon(path))
        return item