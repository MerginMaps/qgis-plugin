import os

from qgis.PyQt import uic
from qgis.PyQt.QtCore import QSettings, Qt, QVariant, QSortFilterProxyModel
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QHeaderView,
    QMessageBox,
    QTreeView,
    QWizard,
)

from qgis.core import QgsProject, QgsLayerTreeNode, QgsLayerTreeModel
from qgis.utils import iface

from .utils import (
    create_basic_qgis_project,
    find_packable_layers,
    find_qgis_files,
    package_layer,
    save_current_project,
)

base_dir = os.path.dirname(__file__)
ui_init_page, base_init_page = uic.loadUiType(os.path.join(base_dir, "ui", "ui_new_proj_init_page.ui"))
ui_local_path_page, base_local_path_page = uic.loadUiType(os.path.join(base_dir, "ui", "ui_get_path_page.ui"))
ui_proj_settings, base_proj_settings = uic.loadUiType(os.path.join(base_dir, "ui", "ui_project_settings_page.ui"))
ui_pack_page, base_pack_page = uic.loadUiType(os.path.join(base_dir, "ui", "ui_packaging_page.ui"))

INIT_PAGE = 0
SAVE_PAGE = 1
CUR_PROJ_PAGE = 2
SETTINGS_PAGE = 3
PACK_PAGE = 4

MIN_MERGIN_PROJ_PATH_LEN = 4


class InitPage(ui_init_page, base_init_page):
    """Initial wizard page with Mergin project source to choose."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.parent = parent
        cur_proj_saved = QgsProject.instance().absoluteFilePath()
        self.btns_page = {
            self.basic_proj_btn: SAVE_PAGE,
            self.cur_proj_no_pack_btn: CUR_PROJ_PAGE,
            self.cur_proj_pack_btn: PACK_PAGE,
        }
        for btn in self.btns_page.keys():
            btn.setAutoExclusive(True)
            btn.clicked.connect(self.selection_changed)
        for btn in (self.cur_proj_no_pack_btn, self.cur_proj_pack_btn):
            btn.setEnabled(bool(cur_proj_saved))
            tip = f"QGIS project:\n{cur_proj_saved}" if cur_proj_saved else "Current QGIS project not saved!"
            btn.setToolTip(tip)
        self.hidden_ledit.hide()
        self.registerField("create_from*", self.hidden_ledit)

    def selection_changed(self):
        for btn in self.btns_page.keys():
            if btn != self.sender():
                btn.setChecked(False)
        self.hidden_ledit.setText("Selection done!")
        self.parent.next()

    def nextId(self):
        """Decide about the next page based on checkable buttons."""
        next_id = INIT_PAGE
        for btn in self.btns_page.keys():
            if btn.isChecked():
                next_id = self.btns_page[btn]
                break
        # make sure current project is saved, if not, open save page instead of locate
        proj_path = QgsProject.instance().absoluteFilePath()
        if next_id == CUR_PROJ_PAGE and not proj_path:
            next_id = SAVE_PAGE
        return next_id


class ChoosePathPage(ui_local_path_page, base_local_path_page):
    """Page for getting local path for saving new Mergin project."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.parent = parent
        self.file_filter = "QGIS projects (*.qgz *.qgs *.QGZ *.QGS)"
        self.file_path = None
        self.dir_path = None
        self.for_current_proj = False

    def nextId(self):
        return SETTINGS_PAGE

    def initializePage(self):
        self.path_ledit.setReadOnly(True)
        self.path_ok_ledit.setHidden(True)
        self.check_directory()

    def setup_browsing(self, question=None, current_proj=None, field=None):
        """This will setup label and signals for browse button."""
        if question is None:
            question = "Choose path"
        self.question_label.setText(question)
        if field:
            self.registerField(field, self.path_ok_ledit)

        if current_proj is not None:
            self.for_current_proj = True
            self.path_ledit.setText(current_proj)
            self.browse_btn.setDisabled(True)
        else:
            self.browse_btn.setEnabled(True)
            self.browse_btn.clicked.connect(self.browse_save)

        self.path_ledit.textChanged.connect(self.check_directory)

    def browse(self, existing=True):
        """Browse for new or existing QGIS project files."""
        settings = QSettings()
        last_dir = settings.value("Mergin/lastProjectDir", "")
        user_path = self.path_ledit.text()
        last_dir = user_path if user_path else last_dir
        if existing:
            self.file_path, filters = QFileDialog.getOpenFileName(
                None, "Choose your project file", last_dir, self.file_filter
            )
        else:
            self.file_path, filters = QFileDialog.getSaveFileName(
                None, "Save project as", last_dir, self.file_filter
            )
            if self.file_path and not (self.file_path.endswith(".qgs") or self.file_path.endswith(".qgz")):
                self.file_path += ".qgz"

        if self.file_path:
            self.path_ledit.setText(self.file_path)
            self.dir_path = os.path.dirname(self.file_path)
            settings = QSettings()
            settings.setValue("Mergin/lastProjectDir", self.dir_path)
        else:
            self.dir_path = None
        self.check_directory()

    def browse_save(self):
        """Browse for file path where to save project."""
        self.browse(existing=False)

    def browse_locate(self):
        """Browse for existing QGIS project file."""
        self.browse()

    def set_info(self, info=None):
        """Set info label text at the bottom of the page. It gets cleared if info is None."""
        info = "" if info is None else info
        self.info_label.setText(info)

    def check_directory(self):
        """Check if entered path is not already a Mergin project dir and has at most a single QGIS project file."""
        cur_text = self.path_ledit.text()
        if not cur_text:
            return
        warn = ""
        cur_dir = cur_text if os.path.isdir(cur_text) else os.path.dirname(cur_text)
        if len(cur_dir) < MIN_MERGIN_PROJ_PATH_LEN:
            return

        if not os.path.exists(cur_dir):
            self.create_warning("The path does not exist")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        qgis_files = find_qgis_files(cur_dir)
        QApplication.processEvents()
        QApplication.restoreOverrideCursor()

        qgis_files_nr = len(qgis_files)
        if self.file_path not in qgis_files:
            qgis_files_nr += 1
        if ".mergin" in os.listdir(cur_dir):
            warn = "Selected directory is already used for a Mergin project."
        if not warn and not self.for_current_proj and qgis_files_nr > 1:
            warn = "Selected directory already contains a QGIS project."
        if warn:
            warn += "\nConsider another directory for saving the project."
            self.create_warning(warn)
        else:
            info = "Selected path is a good candidate for a new Mergin project."
            self.no_warning(info)

    def create_warning(self, problem_info):
        """Make the path editor background red and set the problem description."""
        self.path_ledit.setStyleSheet("background-color: rgb(240, 200, 200);")
        self.path_ledit.setToolTip(problem_info)
        self.set_info(problem_info)
        self.path_ok_ledit.setText("")

    def no_warning(self, info=None):
        """Make the path editor background white and set the info, if specified."""
        self.path_ledit.setStyleSheet("background-color: rgb(255, 255, 255);")
        self.path_ledit.setToolTip(info)
        self.set_info(info)
        self.path_ok_ledit.setText("")
        self.path_ok_ledit.setText(self.path_ledit.text())


class ProjectSettingsPage(ui_proj_settings, base_proj_settings):
    """Wizard page for getting project namespace, name and visibility."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.parent = parent
        self.registerField("project_name*", self.project_name_ledit)
        self.registerField("project_owner", self.project_owner_cbo)
        self.registerField("is_public", self.public_chbox)
        self.populate_namespace_cbo()

    def nextId(self):
        return -1

    def initializePage(self):
        self.parent.get_project_paths()
        proj_name, ext = os.path.splitext(os.path.basename(self.parent.project_file))
        self.project_name_ledit.setText(proj_name)

    def populate_namespace_cbo(self):
        self.project_owner_cbo.addItem(self.parent.username)
        if self.parent.user_organisations:
            self.project_owner_cbo.addItems(
                [o for o in self.parent.user_organisations if self.parent.user_organisations[o] in ["admin", "owner"]]
            )


class LayerTreeProxyModel(QSortFilterProxyModel):
    """Proxy model class for layers tree model to enable user choices of packaging."""

    LAYER_COL = 0
    PACK_COL = 1
    KEEP_COL = 2
    IGNORE_COL = 3

    def __init__(self, parent=None):
        super(LayerTreeProxyModel, self).__init__(parent)
        root = QgsProject.instance().layerTreeRoot()
        self.layer_tree_model = QgsLayerTreeModel(root)
        self.setSourceModel(self.layer_tree_model)
        self.layers_state = dict()
        self.packable = find_packable_layers()
        for tree_layer in root.findLayers():
            lid = tree_layer.layer().id()
            check_col = self.PACK_COL if lid in self.packable else self.KEEP_COL
            self.layers_state[lid] = check_col

    def columnCount(self, parent):
        return 4

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                if section == self.LAYER_COL:
                    return "Layer"
                elif section == self.PACK_COL:
                    return "Package"
                elif section == self.KEEP_COL:
                    return "Keep as is"
                elif section == self.IGNORE_COL:
                    return "Ignore"
        return self.sourceModel().headerData(section, orientation, role)

    def index(self, row, column, parent):
        new_idx = QSortFilterProxyModel.index(self, row, self.LAYER_COL, parent)
        if column == self.LAYER_COL:
            return new_idx
        idx = self.createIndex(row, column, new_idx.internalId())
        return idx

    def toggle_item(self, idx):
        is_checked = self.data(idx, Qt.CheckStateRole) == Qt.Checked
        self.setData(idx, Qt.Unchecked if is_checked else Qt.Checked, Qt.CheckStateRole)

    def map_layer(self, idx):
        if idx.column() == self.LAYER_COL:
            node = self.layer_tree_model.index2node(self.mapToSource(idx))
        else:
            node = self.layer_tree_model.index2node(
                self.mapToSource(self.index(idx.row(), self.LAYER_COL, idx.parent())))
        if not node or not QgsProject.instance().layerTreeRoot().isLayer(node):
            return None
        return node.layer()

    def parent(self, child):
        return QSortFilterProxyModel.parent(self, self.createIndex(child.row(), self.LAYER_COL, child.internalId()))

    def sibling(self, row, column, idx):
        parent = idx.parent()
        return self.index(row, column, parent)

    def data(self, idx, role):
        if idx.column() == self.LAYER_COL:
            return self.layer_tree_model.data(self.mapToSource(idx), role)
        layer = self.map_layer(idx)
        if not layer:
            return QVariant()
        if role == Qt.CheckStateRole or role == Qt.UserRole:
            state = self.layers_state[layer.id()]
            if idx.column() == state:
                return Qt.Checked
            else:
                return Qt.Unchecked
        return QVariant()

    def setData(self, index, value, role):
        if role == Qt.CheckStateRole:
            layer = self.map_layer(index)
            if not layer:
                return False
            if self.PACK_COL <= index.column() <= self.IGNORE_COL:
                packable = layer.id() in self.packable
                if index.column() == self.PACK_COL:
                    checked_col = index.column() if packable else self.KEEP_COL
                else:
                    checked_col = index.column()
                self.layers_state[layer.id()] = checked_col
                idx1 = self.index(index.row(), self.PACK_COL, index.parent())
                idx2 = self.index(index.row(), self.IGNORE_COL, index.parent())
                self.dataChanged.emit(idx1, idx2)
                return True
        return False

    def filterAcceptsRow(self, source_row, source_parent):
        node = self.layer_tree_model.index2node(self.layer_tree_model.index(source_row, self.LAYER_COL, source_parent))
        return bool(self.node_shown(node))

    def node_shown(self, node):
        if not node:
            return False
        if node.nodeType() == QgsLayerTreeNode.NodeGroup:
            if not node.children():
                return False
            for child in node.children():
                if self.node_shown(child):
                    return True
                else:
                    return False
        else:
            layer = node.layer()
            if not layer:
                return False
            return layer.isSpatial()

    def flags(self, idx):
        if idx.column() == self.LAYER_COL:
            return Qt.ItemIsEnabled
        layer = self.map_layer(idx)
        if not layer:
            return Qt.NoItemFlags
        else:
            enabled_flags = Qt.ItemIsEnabled | Qt.ItemIsEditable | Qt.ItemIsUserCheckable
            if idx.column() == self.LAYER_COL:
                return Qt.ItemIsEnabled
            elif idx.column() == self.PACK_COL:
                return enabled_flags if layer.id() in self.packable else Qt.ItemFlags()
            elif idx.column() in (self.KEEP_COL, self.IGNORE_COL):
                return enabled_flags

        return Qt.ItemFlags()


class PackageLayersTreeView(QTreeView):
    """Layers tree view with packaging options to choose."""
    def __init__(self, parent=None):
        super(PackageLayersTreeView, self).__init__(parent)
        self.proxy_model = LayerTreeProxyModel(self)
        self.setModel(self.proxy_model)
        self.expandAll()
        self.header().setStretchLastSection(False)
        self.resizeColumnToContents(0)
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)

        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setEditTriggers(QTreeView.NoEditTriggers)

        self.clicked.connect(self.model().toggle_item)


class PackagingPage(ui_pack_page, base_pack_page):
    """Wizard page for setting individual layers (ignore, copy, keep as is)."""

    def __init__(self, parent=None):
        super(PackagingPage, self).__init__(parent=None)
        self.setupUi(self)
        self.parent = parent
        self.layers_view = PackageLayersTreeView()
        self.layer_tree_lout.addWidget(self.layers_view)

    def nextId(self):
        return SAVE_PAGE


class NewMerginProjectWizard(QWizard):
    """Wizard for creating new Mergin project."""

    def __init__(self, project_manager, username, user_organisations=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.settings = QSettings()
        self.setWindowTitle("Create new Mergin project")
        self.setWizardStyle(QWizard.ClassicStyle)
        self.setDefaultProperty("QComboBox", "currentText", QComboBox.currentTextChanged)
        self.project_manager = project_manager
        self.username = username
        self.user_organisations = user_organisations

        self.init_page = InitPage(self)
        self.setPage(INIT_PAGE, self.init_page)

        where_save = "Where to save the project on your computer?"
        self.save_proj_path_page = ChoosePathPage()
        self.save_proj_path_page.setup_browsing(question=where_save, field="new_project_path*")
        self.setPage(SAVE_PAGE, self.save_proj_path_page)

        cur_loc = "Current QGIS project location"
        cur_proj_path = QgsProject.instance().absoluteFilePath()
        self.cur_proj_page = ChoosePathPage()
        self.cur_proj_page.setup_browsing(question=cur_loc, current_proj=cur_proj_path, field="cur_project_path*")
        self.setPage(CUR_PROJ_PAGE, self.cur_proj_page)

        self.settings_page = ProjectSettingsPage(parent=self)
        self.setPage(SETTINGS_PAGE, self.settings_page)

        self.package_page = PackagingPage(parent=self)
        self.setPage(PACK_PAGE, self.package_page)

        self.cancel_btn = self.button(QWizard.CancelButton)
        self.cancel_btn.clicked.connect(self.cancel_wizard)

        self.currentIdChanged.connect(self.page_change)

        # these are the variables used by the caller
        self.project_namespace = None
        self.project_name = None
        self.project_file = None
        self.project_dir = None
        self.is_public = None
        self.package_data = None

        geom = self.settings.value('Mergin/NewProjWizard/geometry', None)
        if geom is not None:
            self.restoreGeometry(geom)
        else:
            self.setMinimumHeight(400)
            self.setGeometry(200, 200, 600, 450)

    def page_change(self):
        """Run when page has changed."""

    def get_project_paths(self):
        """Get QGIS project path and dir variables."""
        if self.init_page.basic_proj_btn.isChecked() or self.init_page.cur_proj_pack_btn.isChecked():
            self.project_file = self.field("new_project_path")
        elif self.init_page.cur_proj_no_pack_btn.isChecked():
            self.project_file = self.field("cur_project_path")
        else:
            raise  # should not happen
        self.project_dir = os.path.dirname(self.project_file)

    def accept(self):
        self.get_project_paths()
        self.project_namespace = self.field("project_owner")
        self.project_name = self.field("project_name")
        self.is_public = self.field("is_public")
        reload_project = False
        failed_packaging = []

        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()

        if self.init_page.basic_proj_btn.isChecked():
            self.project_file = create_basic_qgis_project(
                project_path=self.project_file, project_name=self.project_name)
            self.iface.addProject(self.project_file)
            # workaround to set proper extent
            self.iface.mapCanvas().zoomToFullExtent()
            QgsProject.instance().write()
            reload_project = True

        elif self.init_page.cur_proj_no_pack_btn.isChecked():
            cur_proj = QgsProject.instance()
            cur_proj.write()
            reload_project = True

        elif self.init_page.cur_proj_pack_btn.isChecked():
            if not save_current_project(self.project_file):
                msg = f"Couldn't save project to specified location:\n{self.project_file}."
                msg += "\n\nCheck the path is writable and try again."
                QMessageBox.warning(None, "Create New Project", msg)
                return
            proxy_model = self.package_page.layers_view.proxy_model
            new_proj = QgsProject.instance()
            new_root = new_proj.layerTreeRoot()
            layers_to_remove = []
            for tree_layer in new_root.findLayers():
                layer = tree_layer.layer()
                layer_state = proxy_model.layers_state[layer.id()]
                if layer_state == proxy_model.PACK_COL:
                    if not package_layer(layer, self.project_dir):
                        failed_packaging.append(layer.name())
                elif layer_state == proxy_model.IGNORE_COL:
                    layers_to_remove.append(layer.id())

            new_proj.removeMapLayers(layers_to_remove)
            new_proj.write()
            reload_project = True

        self.project_dir = QgsProject.instance().absolutePath()

        QApplication.processEvents()
        QApplication.restoreOverrideCursor()

        self.project_manager.create_project(
            self.project_name,
            self.project_dir,
            self.is_public,
            self.project_namespace
        )
        if reload_project:
            self.project_manager.open_project(self.project_dir)

        self.save_geometry()
        super().accept()

        if failed_packaging:
            warn = "Failed to package following layers:\n"
            for failed in failed_packaging:
                warn += f"\n  * {failed}"
            QMessageBox.warning(None, "Error Packaging Layers", warn)

    def cancel_wizard(self):
        self.save_geometry()
        self.reject()

    def save_geometry(self):
        geom = self.saveGeometry()
        self.settings.setValue("Mergin/NewProjWizard/geometry", geom)
