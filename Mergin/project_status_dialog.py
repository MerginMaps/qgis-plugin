import os
from PyQt5.QtWidgets import QDialog, QLabel, QTableWidget, QHeaderView, QTableWidgetItem, \
    QDialogButtonBox, QGridLayout, QTreeView
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QAbstractItemView, QStandardItemModel, QStandardItem, QIcon

from .utils import is_versioned_file


class ProjectStatusDialog(QDialog):

    icons = {
        'added': 'images/plus.svg',
        'removed': 'images/trash.svg',
        'updated': 'images/edit.svg',
        'renamed': 'images/edit.svg'
    }

    def __init__(self, pull_changes, push_changes, push_changes_summary, parent=None):
        super(ProjectStatusDialog, self).__init__(parent)

        self.setWindowTitle("Project status")
        self.table = QTreeView()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["Status"])
        self.table.setModel(self.model)

        self.add_content(pull_changes, 'Server changes')
        self.add_content(push_changes, 'Local changes', push_changes_summary)
        self.table.expandAll()

        box = QDialogButtonBox(
            QDialogButtonBox.Ok,
            centerButtons=True,
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)

        lay = QGridLayout(self)
        lay.addWidget(self.table, 0, 0, 1, 2)
        lay.addWidget(box, 2, 0, 1, 2, Qt.AlignCenter)

        self.resize(640, 640)

    def add_content(self, changes, root_text, changes_summary={}):
        """
        Adds rows with changes info
        :param changes: Dict of added/removed/updated/renamed changes
        :param root_text: Text for the root item
        :param changes_summary: If given and non empty, extra rows are added from geodiff summary.
        :return:
        """
        root_item = QStandardItem(root_text)
        self.model.appendRow(root_item)
        for category in changes:
            for file in changes[category]:
                path = file['path']
                item = self._get_icon_item(category, path)
                if is_versioned_file(path) and path in changes_summary:
                    for sub_item in self._versioned_file_summary_items(changes_summary[path]['geodiff_summary']):
                        item.appendRow(sub_item)
                root_item.appendRow(item)

    def _versioned_file_summary_items(self, geodiff_summary):
        for s in geodiff_summary:
            table_name_item = QStandardItem(s['table'])
            for row in self._table_summary_items(s):
                table_name_item.appendRow(row)
            yield table_name_item

    def _table_summary_items(self, summary):
        return [QStandardItem("{}: {}".format(k, summary[k])) for k in summary if k!='table']

    def _get_icon_item(self, category, text):
        path = os.path.join(os.path.dirname(os.path.realpath(__file__)), self.icons[category])
        item = QStandardItem(text)
        item.setIcon(QIcon(path))
        return item