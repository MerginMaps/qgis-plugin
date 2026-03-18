import json
from enum import Enum
from typing import Optional, Union, List

from qgis.core import QgsProviderRegistry, QgsVectorLayer
from qgis.PyQt.QtCore import Qt, QAbstractListModel, QModelIndex, pyqtSignal
from qgis.PyQt.QtWidgets import QListView
from qgis.PyQt.QtGui import QMouseEvent


class FieldFilterType(str, Enum):
    SINGLE_SELECT = "Single select"
    MULTI_SELECT = "Multi select"
    CHECKBOX = "Checkbox"
    DATE = "Date"
    NUMBER = "Number"
    TEXT = "Text"


def excluded_filtering_providers() -> List[str]:
    """Get list of providers to exclude from layer selection in field filter settings."""
    excluded_providers = QgsProviderRegistry.instance().providerList()
    excluded_providers.remove("ogr")
    excluded_providers.remove("postgres")
    return excluded_providers


def field_filters_to_json(filters: List["FieldFilter"]) -> str:
    """Serialize a list of FieldFilter objects to a JSON string."""
    return json.dumps([f.to_dict() for f in filters])


def field_filters_from_json(data: str) -> List["FieldFilter"]:
    """Deserialize a JSON string into a list of FieldFilter objects."""
    return [FieldFilter.from_dict(item) for item in json.loads(data)]


class FieldFilter:

    def __init__(
        self,
        layer: QgsVectorLayer,
        field_name: str,
        filter_type: FieldFilterType,
        filter_name: str,
    ):
        if not isinstance(layer, QgsVectorLayer):
            raise ValueError("layer must be a QgsVectorLayer")

        if field_name not in layer.fields().names():
            raise ValueError(f"Field '{field_name}' does not exist in layer '{layer.name()}'")

        provider = layer.dataProvider()
        self.provider = provider.name() if provider else ""
        self.layer_id = layer.id()
        self.field_name = field_name
        self.filter_type = filter_type
        self.filter_name = filter_name
        self.sql_expression = ""

    @classmethod
    def from_dict(cls, data: dict) -> "FieldFilter":
        """Create a FieldFilter instance from a dictionary"""
        f = object.__new__(cls)
        f.layer_id = data["layer_id"]
        f.provider = data.get("provider", "")
        f.field_name = data["field_name"]
        f.filter_type = FieldFilterType(data["filter_type"])
        f.filter_name = data["filter_name"]
        f.sql_expression = data.get("sql_expression", "")
        return f

    def to_dict(self) -> dict:
        """Convert the object to a dictionary"""
        return {
            "layer_id": self.layer_id,
            "provider": self.provider,
            "field_name": self.field_name,
            "filter_type": self.filter_type.value,
            "filter_name": self.filter_name,
            "sql_expression": self.sql_expression,
        }


class FieldFilterModel(QAbstractListModel):
    """Model to manage a list of FieldFilter objects, providing methods to add, remove, and reorder filters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filters: list[FieldFilter] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._filters)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.UserRole) -> Union[str, FieldFilter, None]:
        if not index.isValid() or index.row() >= len(self._filters):
            return None
        f = self._filters[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return f.filter_name
        elif role == Qt.ItemDataRole.UserRole:
            return f
        return None

    def add_filter(self, field_filter: FieldFilter):
        """Add filter to the model, notifying views of the change."""
        self.beginInsertRows(QModelIndex(), len(self._filters), len(self._filters))
        self._filters.append(field_filter)
        self.endInsertRows()

    def remove_filter(self, row: int):
        """Remove filter at the specified row, notifying views of the change."""
        if 0 <= row < len(self._filters):
            self.beginRemoveRows(QModelIndex(), row, row)
            self._filters.pop(row)
            self.endRemoveRows()

    def move_filter(self, row: int, offset: int) -> None:
        """Move filter at the specified row by the given offset, notifying views of the change."""
        target = row + offset
        if 0 <= row < len(self._filters) and 0 <= target < len(self._filters):
            self._filters[row], self._filters[target] = self._filters[target], self._filters[row]
            top, bottom = min(row, target), max(row, target)
            self.dataChanged.emit(self.index(top), self.index(bottom))

    def filter_names(self) -> List[str]:
        """Get list of filter names for all filters in the model."""
        return [f.filter_name for f in self._filters]

    def to_json(self) -> str:
        """Serialize the list of filters in the model to a JSON string."""
        return field_filters_to_json(self._filters)

    def load_from_json(self, data: str) -> None:
        """Load filters from a JSON string, replacing existing filters and notifying views of the change."""
        self.beginResetModel()
        self._filters = field_filters_from_json(data)
        self.endResetModel()


class DeselectableListView(QListView):
    """QListView that clears selection when clicking outside items or on the already-selected item."""

    selectionCleared = pyqtSignal(QModelIndex, QModelIndex)

    def mousePressEvent(self, event: Optional[QMouseEvent]) -> None:
        if event:
            index = self.indexAt(event.pos())
            if not index.isValid() or index == self.currentIndex():
                self.blockSignals(True)
                self.clearSelection()
                self.setCurrentIndex(QModelIndex())
                self.blockSignals(False)
                self.selectionCleared.emit(QModelIndex(), QModelIndex())
                return

        super().mousePressEvent(event)
