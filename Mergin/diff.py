import os
import json
import base64
import sqlite3
import tempfile
import xml.etree.ElementTree as ET

from qgis.PyQt.QtCore import (
    QVariant
)

from qgis.PyQt.QtGui import (
    QColor
)

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsFields,
    QgsField,
    QgsProject,
    QgsLayerTreeLayer,
    QgsConditionalStyle,
    QgsSymbolLayerUtils,
    QgsMarkerSymbol,
    QgsLineSymbol,
    QgsFillSymbol,
    QgsRuleBasedRenderer,
    QgsWkbTypes,
    QgsProjectArchive
)

from .utils import (
    pygeodiff,
    get_schema
)

CHANGES_GROUP = "Mergin local changes"

geodiff = pygeodiff.GeoDiff()
geodiff.set_maximum_logger_level(10)

diff_layers_list = []


class ColumnSchema:
    """Describes GPKG table column"""
    def __init__(self, name, datatype, pkey):
        self.name = name
        self.datatype = datatype
        self.pkey = pkey

    def __repr__(self):
        return f'<ColumnSchema {self.name} ({self.datatype})>'


class TableSchema:
    """Describes GPKG table"""
    def __init__(self, name, columns):
        self.name = name
        self.columns = columns

    def geometry_column_index(self):
        """Returns index of the geometry column or -1 if it does not exist"""
        for i, col in enumerate(self.columns):
            if col.datatype == 'geometry':
                return i
        return -1

    def __repr__(self):
        return f'<TableSchema {self.name}>'


def old_value_for_column_by_index(entry_changes, i):
    """Retrieve previous (old) column value for given column index"""
    for ch in entry_changes:
        if ch['column'] == i:
            return ch['old']
    raise ValueError("Expected value for column, but missing")


def get_row_from_db(db_conn, schema_table, entry_changes):
    """
    Fetches a single row from DB's table based on the values of pkeys
    in changeset entry
    """
    c = db_conn.cursor()
    where_bits = []
    for i, col in enumerate(schema_table.columns):
        if col.pkey:
            where_bits.append("{} = {}".format(col.name, old_value_for_column_by_index(entry_changes, i)))

    c.execute('SELECT * FROM {} WHERE {}'.format(schema_table.name, " AND ".join(where_bits)))
    return c.fetchone()


def parse_gpkg_geom_encoding(wkb_with_gpkg_hdr):
    """Parse header of GPKG WKB and return WKB geometry"""
    flag_byte = wkb_with_gpkg_hdr[3]
    envelope_byte = (flag_byte & 14) >> 1
    envelope_size = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64 }[envelope_byte]
    hdr_size = 8 + envelope_size
    wkb = wkb_with_gpkg_hdr[hdr_size:]
    return wkb


def parse_db_schema(db_file):
    """Parse GPKG file schema and return map of tables
    """
    schema_json = get_schema(db_file)

    tables = {}  # key: name, value: TableSchema
    for tbl in schema_json:
        columns = []
        for col in tbl['columns']:
            columns.append(ColumnSchema(col['name'], col['type'], 'primary_key' in col and col['primary_key']))

        tables[tbl['table']] = TableSchema(tbl['table'], columns)
    return tables


def parse_diff(diff_file):
    """
    Parse binary GeoDiff changeset and return map of changes per table
    as follows

    key: table name, value: list of tuples (type, changes)
    """
    tmp_file = tempfile.NamedTemporaryFile(delete=False)
    tmp_file.close()

    geodiff.list_changes(diff_file, tmp_file.name)
    with open(tmp_file.name, encoding="utf-8") as f:
        diff_json = json.load(f)
    os.unlink(tmp_file.name)

    diff_entries = diff_json['geodiff']

    # group diff entries by tables
    diff_tables = {}    # key: table name, value: list of tuples (type, changes)
    for diff_entry in diff_entries:
        entry_table = diff_entry['table']
        entry_type = diff_entry['type']
        entry_changes = diff_entry['changes']

        if entry_table not in diff_tables:
            diff_tables[entry_table] = []
        diff_tables[entry_table].append( (entry_type, entry_changes) )

    return diff_tables


def create_field_list(schema_table):
    """
    Creates QgsFields object from table schema as well as a mapping
    between table columns and fields indices
    """
    columns_to_fields = {}  # some columns (e.g. geometry) may be skipped

    fields = QgsFields()
    for i, column in enumerate(schema_table.columns):
        if column.datatype == 'integer':
            t = QVariant.Int
        elif column.datatype == 'text':
            t = QVariant.String
        elif column.datatype == 'double':
            t = QVariant.Double
        elif column.datatype == 'date':
            t = QVariant.Date
        elif column.datatype == 'datetime':
            t = QVariant.DateTime
        elif column.datatype == 'boolean':
            t = QVariant.Bool
        elif column.datatype == 'blob':
            t = QVariant.QByteArray
        elif column.datatype == 'geometry':
            continue
        else:
            raise ValueError(f"Unknow column type '{column.datatype}' for column '{column.name}'")
        columns_to_fields[i] = fields.count()
        f = QgsField(column.name, t)
        fields.append(f)

    fields.append(QgsField("geometry", QVariant.String))
    old_fields = QgsFields()
    for f in fields:
        old_fields.append(QgsField("_old_" + f.name(), f.type()))
    fields.extend(old_fields)
    fields.append(QgsField("_op", QVariant.String))

    return fields, columns_to_fields


def diff_table_to_features(diff_table, schema_table, fields, cols_to_flds, db_conn=None):
    """
    Converts a diff into list of QgsFeatures.

    Input is list of tuples (type, changes) where type is 'insert'/'update'/'delete'
    and changes is a list of dicts. Each dict with 'column', 'old', 'new' (old/new optional)
    """
    column_names = [column.name for column in schema_table.columns]
    features = []

    fld_geometry_idx = fields.indexOf('geometry')
    fld_old_offset = fld_geometry_idx + 1

    geom_col_index = schema_table.geometry_column_index()

    for entry_type, entry_changes in diff_table:
        f = QgsFeature(fields)
        row = [None for i in range(len(column_names))]

        f["_op"] = entry_type

        # try to fill in unchanged columns from the database
        if entry_type == 'update' and db_conn is not None:
            db_row = get_row_from_db(db_conn, schema_table, entry_changes)

            for i in range(len(db_row)):
                if i == geom_col_index:
                    wkb = parse_gpkg_geom_encoding(db_row[i])
                    g = QgsGeometry()
                    g.fromWkb(wkb)
                    f.setGeometry(g)

                    f[fld_geometry_idx] = g.asWkt()
                    f[fld_geometry_idx + fld_old_offset] = g.asWkt()
                    continue
                else:
                    f[cols_to_flds[i]] = db_row[i]
                    f[cols_to_flds[i] + fld_old_offset] = db_row[i]

        for entry_change in entry_changes:
            i = entry_change['column']
            if 'new' in entry_change:
                value = entry_change['new']
            elif 'old' in entry_change:
                value = entry_change['old']
            else:
                value = '?'

            if i == geom_col_index:
                wkb_with_gpkg_hdr = base64.decodebytes(value.encode('ascii'))
                wkb = parse_gpkg_geom_encoding(wkb_with_gpkg_hdr)
                g = QgsGeometry()
                g.fromWkb(wkb)
                f.setGeometry(g)

                f[fld_geometry_idx] = g.asWkt()
            else:
                f[cols_to_flds[i]] = value

        features.append(f)

    return features


def get_table_name(layer):
    """"Returns name of the GPKG table name for the given vector layer"""
    table_name = ''
    if 'layername' not in layer.source():
        sublayers = layer.dataProvider().subLayers()
        table_name = sublayers[0].split('!!::!!')[1]
    else:
        table_name = layer.source().partition('|layername=')[2]

    return table_name


def get_local_changes(db_file, mp):
    """Creates changeset containing local changes in the given GPKG file."""
    f_name = os.path.split(db_file)[1]
    base_path = mp.fpath_meta(f_name)

    if not os.path.exists(base_path):
        return None

    diff_file = tempfile.NamedTemporaryFile(delete=False)
    diff_file.close()

    geodiff.create_changeset(base_path, db_file, diff_file.name)
    return diff_file.name


def make_local_changes_layer(mp, layer):
    layer_path = layer.source().split("|")[0]
    base_file = mp.fpath_meta(os.path.split(layer_path)[1])
    diff_path = get_local_changes(layer_path, mp)

    if diff_path is None:
        return None, f"Failed to retrieve changes, as there is no base file for layer '{layer.name()}'"

    db_schema = parse_db_schema(layer_path)
    diff = parse_diff(diff_path)
    table_name = get_table_name(layer)

    if not diff or table_name not in diff.keys():
        return None, f"No local changes found in layer '{layer.name()}'"

    fields, cols_to_fields = create_field_list(db_schema[table_name])

    db_conn = None  # no ref. db
    db_conn = sqlite3.connect(base_file)

    features = diff_table_to_features(diff[table_name], db_schema[table_name], fields, cols_to_fields, db_conn)

    # create diff layer
    vl = QgsVectorLayer(f"{QgsWkbTypes.displayString(layer.wkbType())}?crs={layer.sourceCrs().authid()}",
                        f"{layer.name()}-diff", "memory")
    if not vl.isValid():
        return None, f"Failed to create memory layer for local changes"

    vl.dataProvider().addAttributes(fields)
    vl.updateFields()
    vl.dataProvider().addFeatures(features)

    style_diff_layer(vl, db_schema[table_name])
    return vl, ''


def add_diff_layer_to_canvas(layer):
    """Adds diff layer to the QGIS map canvas.

    Layer added to the "Local changes" group (created if not exists).
    If layer with the same name already exists it will be deleted and
    new layer added instead of it.
    """
    layers = QgsProject.instance().mapLayersByName(layer.name())
    if layers:
        QgsProject.instance().removeMapLayers([l.id() for l in layers])

    root = QgsProject.instance().layerTreeRoot()
    group = root.findGroup(CHANGES_GROUP)
    if not group:
        group = root.insertGroup(0, CHANGES_GROUP)

    QgsProject.instance().addMapLayer(layer, False)
    node_layer = QgsLayerTreeLayer(layer)
    group.insertChildNode(0, node_layer)
    group.setExpanded(True)


def style_diff_layer(layer, schema_table):
    """Apply conditional styling and symbology to diff layer"""
    ### setup conditional styles!
    st = layer.conditionalStyles()
    color_red = QColor('#ffdce0')
    color_green = QColor('#dcffe4')
    color_yellow = QColor('#fff5b1')

    # full row for insert / delete
    cs_insert = QgsConditionalStyle()
    cs_insert.setName("insert")
    cs_insert.setRule("_op = 'insert'")
    cs_insert.setBackgroundColor(color_green)
    cs_delete = QgsConditionalStyle()
    cs_delete.setName("delete")
    cs_delete.setRule("_op = 'delete'")
    cs_delete.setBackgroundColor(color_red)
    st.setRowStyles([cs_insert, cs_delete])

    # field style for each updated field
    for column in schema_table.columns:
        if column.datatype == 'geometry':
            col_name = 'geometry'
        else:
            col_name = column.name
        cs = QgsConditionalStyle()
        cs.setName("update")
        cs.setRule(f'"{col_name}" IS NOT "_old_{col_name}"')
        cs.setBackgroundColor(color_yellow)
        st.setFieldStyles(col_name, [cs])

    # set up which fields are shown in the attribute table
    cfg = layer.attributeTableConfig()
    flds = layer.fields()
    for i, fld in enumerate(flds):
        if fld.name().startswith("_old_") or fld.name() == "_op":
            cfg.setColumnHidden(i, True)
    layer.setAttributeTableConfig(cfg)

    # set up styling of the layer
    darker_factor = 150
    if layer.geometryType() == QgsWkbTypes.PointGeometry:
        point_symbol_base = {
            'name': 'circle',
            'outline_style': 'solid',
            'outline_width': '0.4',
            'outline_width_unit': 'MM',
            'size': '2',
            'size_unit': 'MM',
        }
        point_symbol_insert = dict(point_symbol_base)
        point_symbol_insert['color'] = QgsSymbolLayerUtils.encodeColor(color_green)
        point_symbol_insert['outline_color'] = QgsSymbolLayerUtils.encodeColor(color_green.darker(darker_factor))
        point_symbol_update = dict(point_symbol_base)
        point_symbol_update['color'] = QgsSymbolLayerUtils.encodeColor(color_yellow)
        point_symbol_update['outline_color'] = QgsSymbolLayerUtils.encodeColor(color_yellow.darker(darker_factor))
        point_symbol_delete = dict(point_symbol_base)
        point_symbol_delete['color'] = QgsSymbolLayerUtils.encodeColor(color_red)
        point_symbol_delete['outline_color'] = QgsSymbolLayerUtils.encodeColor(color_red.darker(darker_factor))

        root_rule = QgsRuleBasedRenderer.Rule(None)
        root_rule.appendChild(QgsRuleBasedRenderer.Rule(QgsMarkerSymbol.createSimple(point_symbol_insert), 0, 0, "_op = 'insert'", "Insert"))
        root_rule.appendChild(QgsRuleBasedRenderer.Rule(QgsMarkerSymbol.createSimple(point_symbol_update), 0, 0, "_op = 'update'", "Update"))
        root_rule.appendChild(QgsRuleBasedRenderer.Rule(QgsMarkerSymbol.createSimple(point_symbol_delete), 0, 0, "_op = 'delete'", "Delete"))
        r = QgsRuleBasedRenderer(root_rule)
        layer.setRenderer(r)
    elif layer.geometryType() == QgsWkbTypes.LineGeometry:
        line_symbol_base = {
            'capstyle': 'square',
            'joinstyle': 'bevel',
            'line_style': 'solid',
            'line_width': '0.26',
            'line_width_unit': 'MM',
        }
        line_symbol_insert = dict(point_symbol_base)
        line_symbol_insert['line_color'] = QgsSymbolLayerUtils.encodeColor(color_green)
        line_symbol_update = dict(point_symbol_base)
        line_symbol_update['line_color'] = QgsSymbolLayerUtils.encodeColor(color_yellow)
        line_symbol_delete = dict(point_symbol_base)
        line_symbol_delete['line_color'] = QgsSymbolLayerUtils.encodeColor(color_red)

        root_rule = QgsRuleBasedRenderer.Rule(None)
        root_rule.appendChild(QgsRuleBasedRenderer.Rule(QgsLineSymbol.createSimple(line_symbol_insert), 0, 0, "_op = 'insert'", "Insert"))
        root_rule.appendChild(QgsRuleBasedRenderer.Rule(QgsLineSymbol.createSimple(line_symbol_update), 0, 0, "_op = 'update'", "Update"))
        root_rule.appendChild(QgsRuleBasedRenderer.Rule(QgsLineSymbol.createSimple(line_symbol_delete), 0, 0, "_op = 'delete'", "Delete"))
        r = QgsRuleBasedRenderer(root_rule)
        layer.setRenderer(r)
    elif layer.geometryType() == QgsWkbTypes.PolygonGeometry:
        fill_symbol_base = {
            'joinstyle': 'bevel',
            'style': 'solid',
            'outline_style': 'solid',
            'outline_width': '0.26',
            'outline_width_unit': 'MM',
        }
        fill_symbol_insert = dict(point_symbol_base)
        fill_symbol_insert['color'] = QgsSymbolLayerUtils.encodeColor(color_green)
        fill_symbol_insert['outline_color'] = QgsSymbolLayerUtils.encodeColor(color_green.darker(darker_factor))
        fill_symbol_update = dict(point_symbol_base)
        fill_symbol_update['color'] = QgsSymbolLayerUtils.encodeColor(color_yellow)
        fill_symbol_update['outline_color'] = QgsSymbolLayerUtils.encodeColor(color_yellow.darker(darker_factor))
        fill_symbol_delete = dict(point_symbol_base)
        fill_symbol_delete['color'] = QgsSymbolLayerUtils.encodeColor(color_red)
        fill_symbol_delete['outline_color'] = QgsSymbolLayerUtils.encodeColor(color_red.darker(darker_factor))

        root_rule = QgsRuleBasedRenderer.Rule(None)
        root_rule.appendChild(QgsRuleBasedRenderer.Rule(QgsFillSymbol.createSimple(fill_symbol_insert), 0, 0, "_op = 'insert'", "Insert"))
        root_rule.appendChild(QgsRuleBasedRenderer.Rule(QgsFillSymbol.createSimple(fill_symbol_update), 0, 0, "_op = 'update'", "Update"))
        root_rule.appendChild(QgsRuleBasedRenderer.Rule(QgsFillSymbol.createSimple(fill_symbol_delete), 0, 0, "_op = 'delete'", "Delete"))
        r = QgsRuleBasedRenderer(root_rule)
        layer.setRenderer(r)


def cleanup_project(diff_layers):
    """Remove group and diff layers from the project"""

    arc = QgsProjectArchive()
    xml = None
    if QgsProject.instance().isZipped():
        arc.unzip(QgsProject.instance().fileName())
        xml = ET.parse(arc.projectFile())
    else:
        xml = ET.parse(QgsProject.instance().fileName())

    root = xml.getroot()

    # drop any reference to the group
    elements = root.findall(f".//*[@name='{CHANGES_GROUP}']")
    parents = root.findall(f".//*[@name='{CHANGES_GROUP}']/..")
    for i, p in enumerate(parents):
        p.remove(elements[i])

    # drop layer-related elements
    for lid in diff_layers:
        # <layer> and <layer-setting> items
        elements = root.findall(f".//*[@id='{lid}']")
        parents = root.findall(f".//*[@id='{lid}']/..")
        for i, p in enumerate(parents):
            p.remove(elements[i])

        # <maplayer> item
        elements = root.findall(f".//maplayer/*[.='{lid}']/..")
        parents = root.findall(f".//maplayer/*[.='{lid}']/../..")
        for i, p in enumerate(parents):
            p.remove(elements[i])

        # <layer> item
        elements = root.findall(f".//*[.='{lid}']")
        parents = root.findall(f".//*[.='{lid}']/..")
        for i, p in enumerate(parents):
            p.remove(elements[i])

    if QgsProject.instance().isZipped():
        with open(arc.projectFile(), 'wb') as f:
            f.write("<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>".encode('utf8'))
            xml.write(f)
        arc.zip(QgsProject.instance().fileName())
    else:
        with open(QgsProject.instance().fileName(), "wb") as f:
            f.write("<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>".encode('utf8'))
            xml.write(f)
