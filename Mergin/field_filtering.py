import json
from enum import Enum
from typing import Optional, Union, List

from qgis.core import QgsProviderRegistry, QgsVectorLayer, QgsFields, QgsProject, QgsMapLayer, Qgis
from qgis.PyQt.QtCore import Qt, QAbstractListModel, QModelIndex, pyqtSignal, QMetaType
from qgis.PyQt.QtWidgets import QListView
from qgis.PyQt.QtGui import QMouseEvent


SQL_PLACEHOLDER_VALUE = "@@value@@"
SQL_PLACEHOLDER_VALUE_FROM = "@@value_from@@"
SQL_PLACEHOLDER_VALUE_TO = "@@value_to@@"


class FieldFilterType(str, Enum):
    TEXT = "Text"
    NUMBER = "Number"
    DATE = "Date"
    CHECKBOX = "Checkbox"
    SINGLE_SELECT = "Single select"
    MULTI_SELECT = "Multi select"


def excluded_filtering_providers() -> List[str]:
    """Get list of providers to exclude from layer selection in field filter settings."""
    excluded_providers = QgsProviderRegistry.instance().providerList()
    excluded_providers.remove("ogr")
    excluded_providers.remove("postgres")
    return excluded_providers


def excluded_layers_list() -> List[QgsMapLayer]:
    excluded_layers: List[QgsMapLayer] = []

    project_layers = QgsProject.instance().mapLayers()

    layer: QgsMapLayer
    for _, layer in project_layers.items():
        if layer.type() != Qgis.LayerType.Vector:
            excluded_layers.append(layer)
            continue

        dp = layer.dataProvider()

        if dp.name() != "ogr":
            excluded_layers.append(layer)
            continue

        # storage type in OGR should return driver name of the datasource
        if not hasattr(dp, "storageType") or dp.storageType() != "GPKG":
            excluded_layers.append(layer)
            continue

    return excluded_layers


def field_filters_to_json(filters: List["FieldFilter"]) -> str:
    """Serialize a list of FieldFilter objects to a JSON string."""
    return json.dumps([f.to_dict() for f in filters])


def field_filters_from_json(data: str) -> List["FieldFilter"]:
    """Deserialize a JSON string into a list of FieldFilter objects."""
    return [FieldFilter.from_dict(item) for item in json.loads(data)]


class FieldFilter:

    def __init__(
        self,
        layer: Optional[QgsVectorLayer],
        field_name: str,
        filter_type: FieldFilterType,
        filter_name: str,
    ):
        if layer is not None and not isinstance(layer, QgsVectorLayer):
            raise ValueError("layer must be a QgsVectorLayer")

        if layer is not None and field_name not in layer.fields().names():
            raise ValueError(f"Field '{field_name}' does not exist in layer '{layer.name()}'")

        self.provider = ""
        self.layer_id = ""

        if layer is not None:
            provider = layer.dataProvider()
            self.provider = provider.name() if provider else ""
            self.layer_id = layer.id()

        self.field_name = field_name
        self.filter_type = filter_type
        self.filter_name = filter_name
        self.sql_expression = ""

        if layer is not None:
            self._generate_sql_expression()

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
        if not f.sql_expression:
            f._generate_sql_expression()
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

    @property
    def is_postgres(self) -> bool:
        return self.provider == "postgres"

    def __eq__(self, value: object) -> bool:
        if not isinstance(value, FieldFilter):
            return NotImplemented
        return (
            self.layer_id == value.layer_id
            and self.provider == value.provider
            and self.field_name == value.field_name
            and self.filter_type == value.filter_type
            and self.filter_name == value.filter_name
        )

    def _generate_sql_expression(self) -> None:
        """Generate a SQL WHERE clause template with named value placeholders.

        Every placeholder is replaced entirely by the substituting code, which must
        supply a complete, properly-quoted SQL literal for the target provider.

        Placeholders:
            SQL_PLACEHOLDER_VALUE
                            — single value (TEXT, CHECKBOX, SINGLE_SELECT)
                              e.g. '%hello%' for LIKE, 'text', 42, true
                        SQL_PLACEHOLDER_VALUE_FROM
                                                        — lower bound of a range (NUMBER, DATE)
                              e.g. 10, '2024-01-01'
                        SQL_PLACEHOLDER_VALUE_TO
                                                        — upper bound of a range (NUMBER, DATE)
        """
        field = f'"{self.field_name}"'

        if self.filter_type == FieldFilterType.TEXT:
            op = "ILIKE" if self.is_postgres else "LIKE"
            cast = self._cast_field(field)
            expr = f"{cast} {op} '%{SQL_PLACEHOLDER_VALUE}%'"

        elif self.filter_type == FieldFilterType.NUMBER:
            cast = self._cast_field(field)
            expr = f"{cast} >= {SQL_PLACEHOLDER_VALUE_FROM} AND {cast} <= {SQL_PLACEHOLDER_VALUE_TO}"

        elif self.filter_type == FieldFilterType.DATE:
            cast = self._cast_field(field)
            expr = f"{cast} >= '{SQL_PLACEHOLDER_VALUE_FROM}' AND {cast} <= '{SQL_PLACEHOLDER_VALUE_TO}'"

        elif self.filter_type == FieldFilterType.CHECKBOX:
            expr = f"{field} = {SQL_PLACEHOLDER_VALUE}"

        elif self.filter_type in (FieldFilterType.SINGLE_SELECT, FieldFilterType.MULTI_SELECT):
            expr = f"{field} IS {SQL_PLACEHOLDER_VALUE}"

        else:
            expr = ""

        self.sql_expression = expr

    def apply_values(
        self,
        value=None,
        value_from=None,
        value_to=None,
    ) -> str:
        """Replace placeholders in sql_expression with properly quoted SQL literals. Raises ValueError if sql_expression is empty."""
        if not self.sql_expression:
            self._generate_sql_expression()

        expr = self.sql_expression

        uses_value = SQL_PLACEHOLDER_VALUE in expr
        uses_value_from = SQL_PLACEHOLDER_VALUE_FROM in expr
        uses_value_to = SQL_PLACEHOLDER_VALUE_TO in expr

        if uses_value and value is None:
            raise ValueError("sql_expression requires 'value' but it was not provided")
        if uses_value_from and value_from is None:
            raise ValueError("sql_expression requires 'value_from' but it was not provided")
        if uses_value_to and value_to is None:
            raise ValueError("sql_expression requires 'value_to' but it was not provided")

        if value is not None and not uses_value:
            raise ValueError(f"'value' was provided but sql_expression has no {SQL_PLACEHOLDER_VALUE} placeholder")
        if value_from is not None and not uses_value_from:
            raise ValueError(
                f"'value_from' was provided but sql_expression has no {SQL_PLACEHOLDER_VALUE_FROM} placeholder"
            )
        if value_to is not None and not uses_value_to:
            raise ValueError(
                f"'value_to' was provided but sql_expression has no {SQL_PLACEHOLDER_VALUE_TO} placeholder"
            )

        if value is not None:
            if self.filter_type == FieldFilterType.TEXT:
                escaped = str(value).replace("'", "''")
                literal = f"'%{escaped}%'"
                expr = expr.replace(SQL_PLACEHOLDER_VALUE, literal)

            elif self.filter_type == FieldFilterType.CHECKBOX:
                if self.is_postgres:
                    literal = "TRUE" if value else "FALSE"
                else:
                    literal = "1" if value else "0"
                expr = expr.replace(SQL_PLACEHOLDER_VALUE, literal)

            elif self.filter_type == FieldFilterType.SINGLE_SELECT:
                escaped = str(value).replace("'", "''")
                expr = expr.replace(SQL_PLACEHOLDER_VALUE, f"'{escaped}'")

        if value_from is not None:
            if self.filter_type == FieldFilterType.DATE:
                expr = expr.replace(SQL_PLACEHOLDER_VALUE_FROM, f"'{value_from}'")
            else:
                expr = expr.replace(SQL_PLACEHOLDER_VALUE_FROM, str(value_from))

        if value_to is not None:
            if self.filter_type == FieldFilterType.DATE:
                expr = expr.replace(SQL_PLACEHOLDER_VALUE_TO, f"'{value_to}'")
            else:
                expr = expr.replace(SQL_PLACEHOLDER_VALUE_TO, str(value_to))

        return expr

    def _cast_field(self, field: str) -> str:
        """Wrap field in a CAST expression matching the filter type and provider.

        Cast types:
            TEXT    — CHARACTER (OGR) / text (PostgreSQL)
            NUMBER  — FLOAT (OGR) / numeric (PostgreSQL)
            DATE    — CHARACTER  (OGR) / timestamp (PostgreSQL)
        """
        if self.filter_type == FieldFilterType.TEXT:
            cast_type = "text" if self.is_postgres else "CHARACTER"
        elif self.filter_type == FieldFilterType.NUMBER:
            cast_type = "numeric" if self.is_postgres else "FLOAT"
        elif self.filter_type == FieldFilterType.DATE:
            cast_type = "timestamp" if self.is_postgres else "CHARACTER"
        else:
            return field

        return f"CAST({field} AS {cast_type})"


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

    def replace_filter(self, row: int, field_filter: FieldFilter) -> None:
        """Replace filter at the specified row, notifying views of the change."""
        if 0 <= row < len(self._filters):
            self._filters[row] = field_filter
            index = self.index(row)
            self.dataChanged.emit(index, index)

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
            if not index.isValid():
                self.blockSignals(True)
                self.clearSelection()
                self.setCurrentIndex(QModelIndex())
                self.blockSignals(False)
                self.selectionCleared.emit(QModelIndex(), QModelIndex())
                return

        super().mousePressEvent(event)


def get_fields_for_checkbox(layer: QgsVectorLayer) -> QgsFields:
    """Get fields of type boolean or with checkbox editor widget from the given layer."""
    fields = QgsFields()
    if layer and layer.isValid() and isinstance(layer, QgsVectorLayer):
        for field in layer.fields():
            if field.type() == QMetaType.Type.Bool or field.editorWidgetSetup().type() == "CheckBox":
                fields.append(field)
    return fields
