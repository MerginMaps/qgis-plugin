import shutil
from datetime import datetime, timezone
from urllib.error import URLError, HTTPError
import configparser
import os
from osgeo import gdal
import pathlib
import platform
import urllib.parse
import urllib.request

from qgis.PyQt.QtCore import QSettings, QVariant
from qgis.PyQt.QtWidgets import QMessageBox, QFileDialog

from qgis.core import (
    NULL,
    Qgis,
    QgsApplication,
    QgsAuthMethodConfig,
    QgsCoordinateReferenceSystem,
    QgsDataProvider,
    QgsEditorWidgetSetup,
    QgsExpressionContextUtils,
    QgsField,
    QgsMapLayerType,
    QgsMarkerSymbol,
    QgsMeshDataProvider,
    QgsProject,
    QgsRaster,
    QgsRasterDataProvider,
    QgsRasterFileWriter,
    QgsRasterLayer,
    QgsRasterPipe,
    QgsRasterProjector,
    QgsVectorDataProvider,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from .mergin.utils import int_version
from .mergin.merginproject import MerginProject


try:
    from .mergin import InvalidProject
    from .mergin.client import MerginClient, ClientError, LoginError
    from .mergin.client_pull import download_project_async, download_project_is_running, \
                                    download_project_finalize, download_project_cancel
    from .mergin.client_pull import pull_project_async, pull_project_is_running, \
                                    pull_project_finalize, pull_project_cancel
    from .mergin.client_push import push_project_async, push_project_is_running, \
                                    push_project_finalize, push_project_cancel
    from .mergin.report import create_report
except ImportError:
    import sys
    this_dir = os.path.dirname(os.path.realpath(__file__))
    path = os.path.join(this_dir, 'mergin_client.whl')
    sys.path.append(path)
    from mergin.client import MerginClient, ClientError, InvalidProject, LoginError
    from mergin.client_pull import download_project_async, download_project_is_running, \
                                   download_project_finalize, download_project_cancel
    from mergin.client_pull import pull_project_async, pull_project_is_running, \
                                   pull_project_finalize, pull_project_cancel
    from mergin.client_push import push_project_async, push_project_is_running, \
                                   push_project_finalize, push_project_cancel
    from .mergin.report import create_report

MERGIN_URL = 'https://public.cloudmergin.com'
MERGIN_LOGS_URL = 'https://g4pfq226j0.execute-api.eu-west-1.amazonaws.com/mergin_client_log_submit'

QGIS_NET_PROVIDERS = ("WFS", "arcgisfeatureserver", "arcgismapserver", "geonode", "ows", "wcs", "wms", "vectortile")
QGIS_DB_PROVIDERS = ("postgres", "mssql", "oracle", "hana", "postgresraster", "DB2")
QGIS_MESH_PROVIDERS = ("mdal", "mesh_memory")
QGIS_FILE_BASED_PROVIDERS = ("ogr", "gdal", "spatialite", "delimitedtext", "gpx", "mdal", "grass", "grassraster")
PACKABLE_PROVIDERS = ("ogr", "gdal", "delimitedtext", "gpx", "postgres", "memory")

PROJS_PER_PAGE = 50


class PackagingError(Exception):
    pass


class FieldConverter(QgsVectorFileWriter.FieldValueConverter):
    """
    Custom field value converter renaming fid attribute if it has non-unique values preventing the column to be a
    proper unique FID attribute.
    """
    def __init__(self, layer):
        QgsVectorFileWriter.FieldValueConverter.__init__(self)
        self.layer = layer
        self.fid_idx = None
        self.fid_unique = False
        self.check_fid_unique()

    def check_has_fid_field(self):
        fid_idx = self.layer.fields().lookupField("fid")
        if fid_idx >= 0:
            self.fid_idx = fid_idx
            return True
        else:
            self.fid_idx = None
            return False

    def check_fid_unique(self):
        if not self.check_has_fid_field():
            self.fid_unique = True
            return
        self.fid_unique = len(self.layer.uniqueValues(self.fid_idx)) == self.layer.featureCount()

    def get_fid_replacement(self):
        suff = 1
        while True:
            replacement = f"fid_{suff}"
            if self.layer.fields().lookupField(replacement) < 0:
                return replacement
            suff += 1

    def fieldDefinition(self, field):
        """If the original FID column has non-unique values, rename it."""
        idx = self.layer.fields().indexOf(field.name())
        if self.fid_unique or idx != self.fid_idx:
            return self.layer.fields()[idx]
        fid_repl = self.get_fid_replacement()
        return QgsField(fid_repl, QVariant.Int)

    def convert(self, idx, value):
        """Leave value as is."""
        return value


def find_qgis_files(directory):
    qgis_files = []
    for root, dirs, files in os.walk(directory):
        for f in files:
            _, ext = os.path.splitext(f)
            if ext in ['.qgs', '.qgz']:
                qgis_files.append(os.path.join(root, f))
    return qgis_files


def get_mergin_auth():
    settings = QSettings()
    save_credentials = settings.value('Mergin/saveCredentials', 'false').lower() == 'true'
    mergin_url = settings.value('Mergin/server', MERGIN_URL)
    auth_manager = QgsApplication.authManager()
    if not save_credentials or not auth_manager.masterPasswordHashInDatabase():
        return mergin_url, '', ''

    authcfg = settings.value('Mergin/authcfg', None)
    cfg = QgsAuthMethodConfig()
    auth_manager.loadAuthenticationConfig(authcfg, cfg, True)
    url = cfg.uri()
    username = cfg.config('username')
    password = cfg.config('password')
    return url, username, password


def set_mergin_auth(url, username, password):
    settings = QSettings()
    authcfg = settings.value('Mergin/authcfg', None)
    cfg = QgsAuthMethodConfig()
    auth_manager = QgsApplication.authManager()
    auth_manager.setMasterPassword()
    auth_manager.loadAuthenticationConfig(authcfg, cfg, True)

    if cfg.id():
        cfg.setUri(url)
        cfg.setConfig("username", username)
        cfg.setConfig("password", password)
        auth_manager.updateAuthenticationConfig(cfg)
    else:
        cfg.setMethod("Basic")
        cfg.setName("mergin")
        cfg.setUri(url)
        cfg.setConfig("username", username)
        cfg.setConfig("password", password)
        auth_manager.storeAuthenticationConfig(cfg)
        settings.setValue('Mergin/authcfg', cfg.id())

    settings.setValue('Mergin/server', url)


def get_qgis_proxy_config(url=None):
    """Check if a proxy is enabled and needed for the given url. Return the settings and additional info."""
    proxy_config = None
    s = QSettings()
    proxy_enabled = s.value("proxy/proxyEnabled", False, type=bool)
    if proxy_enabled:
        proxy_type = s.value("proxy/proxyType")
        if proxy_type not in ("HttpProxy", "HttpCachingProxy"):
            raise ClientError(f"Not supported proxy server type ({proxy_type})")
        excluded = [e.rstrip("/") for e in s.value("proxy/proxyExcludedUrls", "").split("|")]
        if url is not None and url.rstrip("/") in excluded:
            return proxy_config
        proxy_config = dict()
        proxy_config["url"] = s.value("proxy/proxyHost", None)
        if proxy_config["url"] is None:
            raise ClientError("No URL given for proxy server")
        proxy_config["port"] = s.value("proxy/proxyPort", 3128)
        auth_conf_id = s.value("proxy/authcfg", None)
        if auth_conf_id:
            auth_manager = QgsApplication.authManager()
            auth_conf = QgsAuthMethodConfig()
            auth_manager.loadAuthenticationConfig(auth_conf_id, auth_conf, True)
            proxy_config["user"] = auth_conf.configMap()["username"]
            proxy_config["password"] = auth_conf.configMap()["password"]
        else:
            proxy_config["user"] = s.value("proxy/proxyUser", None)
            proxy_config["password"] = s.value("proxy/proxyPassword", None)
    return proxy_config


def create_mergin_client():
    url, username, password = get_mergin_auth()
    settings = QSettings()
    auth_token = settings.value('Mergin/auth_token', None)
    proxy_config = get_qgis_proxy_config(url)
    if auth_token:
        mc = MerginClient(url, auth_token, username, password, get_plugin_version(), proxy_config)
        # check token expiration
        delta = mc._auth_session['expire'] - datetime.now(timezone.utc)
        if delta.total_seconds() > 1:
            return mc

    if not (username and password):
        raise ClientError()

    try:
        mc = MerginClient(url, None, username, password, get_plugin_version(), proxy_config)
    except (URLError, ClientError) as e:
        QgsApplication.messageLog().logMessage(str(e))
        raise
    settings.setValue('Mergin/auth_token', mc._auth_session['token'])
    return MerginClient(url, mc._auth_session['token'], username, password, get_plugin_version(), proxy_config)


def get_qgis_version_str():
    """ Returns QGIS verion as 'MAJOR.MINOR.PATCH', for example '3.10.6' """
    # there's also Qgis.QGIS_VERSION which is string but also includes release name (possibly with unicode characters)
    qgis_ver_int = Qgis.QGIS_VERSION_INT
    qgis_ver_major = qgis_ver_int // 10000
    qgis_ver_minor = (qgis_ver_int % 10000) // 100
    qgis_ver_patch = (qgis_ver_int % 100)
    return "{}.{}.{}".format(qgis_ver_major, qgis_ver_minor, qgis_ver_patch)


def plugin_version():
    with open(os.path.join(os.path.dirname(__file__), "metadata.txt"), 'r') as f:
        config = configparser.ConfigParser()
        config.read_file(f)
    return config["general"]["version"]


def get_plugin_version():
    version = plugin_version()
    return "Plugin/" + version + " QGIS/" + get_qgis_version_str()


def is_versioned_file(file):
    """ Check if file is compatible with geodiff lib and hence suitable for versioning.

    :param file: file path
    :type file: str
    :returns: if file is compatible with geodiff lib
    :rtype: bool
    """
    diff_extensions = ['.gpkg', '.sqlite']
    f_extension = os.path.splitext(file)[1]
    return f_extension in diff_extensions


def send_logs(username, logfile):
    """ Send mergin-client logs to dedicated server

    :param logfile: path to logfile
    :returns: name of submitted file, error message
    """
    mergin_url, _, _ = get_mergin_auth()
    system = platform.system().lower()
    version = plugin_version()
    # also read global mergin client log
    global_log_file = os.environ.get('MERGIN_CLIENT_LOG', None)

    params = {
        "app": "plugin-{}-{}".format(system, version),
        "username": username
    }
    url = MERGIN_LOGS_URL + "?" + urllib.parse.urlencode(params)
    header = {"content-type": "text/plain"}

    meta = "Plugin: {} \nQGIS: {} \nSystem: {} \nMergin URL: {} \nMergin user: {} \n--------------------------------\n\n"\
        .format(
            version,
            get_qgis_version_str(),
            system,
            mergin_url,
            username
        )

    global_logs = b""
    if global_log_file and os.path.exists(global_log_file):
        with open(global_log_file, 'rb') as f:
            if os.path.getsize(global_log_file) > 100 * 1024:
                f.seek(-100 * 1024, os.SEEK_END)
            global_logs = f.read() + b"\n--------------------------------\n\n"

    with open(logfile, 'rb') as f:
        if os.path.getsize(logfile) > 512 * 1024:
            f.seek(-512 * 1024, os.SEEK_END)
        logs = f.read()

    payload = meta.encode() + global_logs + logs
    try:
        req = urllib.request.Request(url, data=payload, headers=header)
        resp = urllib.request.urlopen(req)
        log_file_name = resp.read().decode()
        if resp.msg != 'OK':
            return None, str(resp.reason)
        return log_file_name, None
    except (HTTPError, URLError) as e:
        return None, str(e)


def validate_mergin_url(url):
    """
    Validation of mergin URL by pinging. Checks if URL points at compatible Mergin server.
    :param url: String Mergin URL to ping.
    :return: String error message as result of validation. If None, URL is valid.
    """
    try:
        mc = MerginClient(url, proxy_config=get_qgis_proxy_config(url))
        if not mc.is_server_compatible():
            return 'Incompatible Mergin server'
    # Valid but not Mergin URl
    except ClientError:
        return "Invalid Mergin URL"
    # Cannot parse URL
    except ValueError:
        return "Invalid URL"
    return None


def same_dir(dir1, dir2):
    """Check if the two directory are the same."""
    if not dir1 or not dir2:
        return False
    path1 = pathlib.Path(dir1)
    path2 = pathlib.Path(dir2)
    return path1 == path2


def get_new_qgis_project_filepath(project_name=None):
    """
    Get path for a new QGIS project. If name is not None, only ask for a directory.
    :name: filename of new project
    :return: string with file path, or None on cancellation
    """
    settings = QSettings()
    last_dir = settings.value("Mergin/lastUsedDownloadDir", str(pathlib.Path.home()))
    if project_name is not None:
        dest_dir = QFileDialog.getExistingDirectory(None, "Destination directory", last_dir, QFileDialog.ShowDirsOnly)
        project_file = os.path.abspath(os.path.join(dest_dir, project_name))
    else:
        project_file, filters = QFileDialog.getSaveFileName(
            None, "Save QGIS project", "", "QGIS projects (*.qgz *.qgs)")
    if project_file:
        if not (project_file.endswith(".qgs") or project_file.endswith(".qgz")):
            project_file += ".qgz"
        return project_file
    return None


def unsaved_project_check():
    """
    Check if current QGIS project has some unsaved changes.
    Let the user decide if the changes are to be saved before continuing.
    :return: True if previous method should continue, False otherwise
    :type: boolean
    """
    if (
        any(
            [
                type(layer) is QgsVectorLayer and layer.isModified()
                for layer in QgsProject.instance().mapLayers().values()
            ]
        )
        or QgsProject.instance().isDirty()
    ):
        msg = "There are some unsaved changes. Do you want save them before continue?"
        btn_reply = QMessageBox.warning(
            None, "Unsaved changes", msg, QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
        )
        if btn_reply == QMessageBox.Yes:
            for layer in QgsProject.instance().mapLayers().values():
                if type(layer) is QgsVectorLayer and layer.isModified():
                    layer.commitChanges()
            if QgsProject.instance().isDirty():
                if QgsProject.instance().fileName():
                    QgsProject.instance().write()
                else:
                    project_file = get_new_qgis_project_filepath()
                    if project_file:
                        QgsProject.instance().setFileName(project_file)
                        write_ok = QgsProject.instance().write()
                        if not write_ok:
                            QMessageBox.warning(None, "Error Saving Project",
                                                "QGIS project was not saved properly. Cancelling...")
                            return False
                    else:
                        return False
            return True
        elif btn_reply == QMessageBox.No:
            return True
        else:
            return False
    return True


def save_vector_layer_as_gpkg(layer, target_dir, update_datasource=False):
    """Save layer as a single table GeoPackage in the target_dir. Update the original layer datasource if needed.
    If the original layer has already a fid column with non-unique values, it will be renamed to first free fid_x.
    """
    layer_name = remove_forbidden_chars("_".join(layer.name().split()))
    layer_filename = get_unique_filename(os.path.join(target_dir, f"{layer_name}.gpkg"))
    transform_context = QgsProject.instance().transformContext()
    writer_opts = QgsVectorFileWriter.SaveVectorOptions()
    writer_opts.fileEncoding = "UTF-8"
    writer_opts.layerName = layer_name
    writer_opts.driverName = "GPKG"
    if layer.fields().lookupField("fid") >= 0:
        converter = FieldConverter(layer)
        writer_opts.fieldValueConverter = converter
    res, err = QgsVectorFileWriter.writeAsVectorFormatV2(layer, layer_filename, transform_context, writer_opts)
    if res != QgsVectorFileWriter.NoError:
        return layer_filename, f"Couldn't properly save layer: {layer_filename}. \n{err}"
    if update_datasource:
        provider_opts = QgsDataProvider.ProviderOptions()
        provider_opts.fileEncoding = "UTF-8"
        provider_opts.layerName = layer_name
        provider_opts.driverName = "GPKG"
        datasource = f"{layer_filename}|layername={layer_name}"
        layer.setDataSource(datasource, layer_name, "ogr", provider_opts)
    return layer_filename, None


def create_basic_qgis_project(project_path=None, project_name=None):
    """
    Create a basic QGIS project with OSM background and a simple vector layer.
    :return: Project file path on successful creation of a new project, None otherwise
    """
    if project_path is None:
        project_path = get_new_qgis_project_filepath(project_name=project_name)
    if project_path is None:
        return False
    new_project = QgsProject()
    crs = QgsCoordinateReferenceSystem()
    crs.createFromString("EPSG:3857")
    new_project.setCrs(crs)
    new_project.setFileName(project_path)
    osm_url = "crs=EPSG:3857&type=xyz&zmin=0&zmax=19&url=http://tile.openstreetmap.org/{z}/{x}/{y}.png"
    osm_layer = QgsRasterLayer(osm_url, "OpenStreetMap", "wms")
    new_project.addMapLayer(osm_layer)

    mem_uri = "Point?crs=epsg:3857"
    mem_layer = QgsVectorLayer(mem_uri, "Survey points", "memory")
    res = mem_layer.dataProvider().addAttributes([
        QgsField("date", QVariant.DateTime),
        QgsField("notes", QVariant.String),
        QgsField("photo", QVariant.String),
    ])
    mem_layer.updateFields()
    vector_fname, err = save_vector_layer_as_gpkg(mem_layer, os.path.dirname(project_path))
    if err:
        QMessageBox.warning(None, "Error Creating New Project", f"Couldn't save vector layer to:\n{vector_fname}")
    vector_layer = QgsVectorLayer(vector_fname, "Survey", "ogr")
    symbol = QgsMarkerSymbol.createSimple({
        'name': 'circle', 'color': '#d73027', 'size': '3', "outline_color": '#e8e8e8', 'outline_style': 'solid',
        'outline_width': '0.4'
    })
    vector_layer.renderer().setSymbol(symbol)
    fid_ws = QgsEditorWidgetSetup("Hidden", {})
    vector_layer.setEditorWidgetSetup(0, fid_ws)
    datetime_config = {
        'allow_null': True, 'calendar_popup': True, 'display_format': 'yyyy-MM-dd HH:mm:ss',
        'field_format': 'yyyy-MM-dd HH:mm:ss', 'field_iso_format': False
    }
    datetime_ws = QgsEditorWidgetSetup("DateTime", datetime_config)
    vector_layer.setEditorWidgetSetup(1, datetime_ws)
    photo_config = {
        'DocumentViewer': 1, 'DocumentViewerHeight': 0, 'DocumentViewerWidth': 0, 'FileWidget': True,
        'FileWidgetButton': True, 'FileWidgetFilter': '', 'RelativeStorage': 1, 'StorageMode': 0,
        'PropertyCollection': {'name': NULL, 'properties': {}, 'type': 'collection'},
    }
    photo_ws = QgsEditorWidgetSetup("ExternalResource", photo_config)
    vector_layer.setEditorWidgetSetup(3, photo_ws)
    new_project.addMapLayer(vector_layer)

    write_success = new_project.write()
    if not write_success:
        QMessageBox.warning(None, "Error Creating New Project", f"Couldn't create new project:\n{project_path}")
        return None
    return project_path


def set_qgis_project_relative_paths(qgis_project):
    """Check if given QGIS project is set up for relative paths. If not, try to change this setting."""
    abs_paths, ok = qgis_project.readEntry("Paths", "/Absolute")
    if ok and abs_paths == "true":
        _ = qgis_project.writeEntry("Paths", "/Absolute", "false")


def save_current_project(project_path, warn=False, relative_paths=True):
    """Save current QGIS project to project_path. Set the project to use relative paths if relative_paths is True."""
    cur_project = QgsProject.instance()
    if relative_paths:
        set_qgis_project_relative_paths(cur_project)
    cur_project.setFileName(project_path)
    write_success = cur_project.write()
    if not write_success and warn:
        QMessageBox.warning(None, "Error Creating Project", f"Couldn't save project to:\n{project_path}")
        return False
    return True


def remove_forbidden_chars(text, forbidden="\\/:*?\"'<>|()"):
    """Remove forbidden characters from the text."""
    for c in forbidden:
        text = text.replace(c, "")
    return text


def get_unique_filename(filename):
    """Check if the filename exists. Try append a number to get a unique filename."""
    if not os.path.exists(filename) and os.path.exists(os.path.dirname(filename)):
        return filename
    file_path_name, ext = os.path.splitext(filename)
    i = 1
    new_filename = f"{file_path_name}_{{}}{ext}"
    while os.path.isfile(new_filename.format(i)):
        i += 1
    return new_filename.format(i)


def datasource_filepath(layer):
    """Check if layer datasource is file-based and return the path, or None otherwise."""
    dp = layer.dataProvider()
    if dp.name() not in QGIS_FILE_BASED_PROVIDERS:
        return None
    if isinstance(dp, (QgsRasterDataProvider, QgsMeshDataProvider,)):
        ds_uri = dp.dataSourceUri()
    elif isinstance(dp, QgsVectorDataProvider):
        if dp.storageType() in ("GPKG", "GPX", "GeoJSON"):
            ds_uri = dp.dataSourceUri().split("|")[0]
        elif dp.storageType() == "Delimited text file":
            ds_uri = dp.dataSourceUri().split("?")[0].replace("file://", "")
        else:
            ds_uri = dp.dataSourceUri()
    else:
        ds_uri = None
    return ds_uri if os.path.isfile(ds_uri) else None


def is_layer_packable(layer):
    """Check if layer can be packaged for a Mergin project."""
    dp = layer.dataProvider()
    if dp is None:
        # Vector tile layers have no provider
        return False
    provider_name = dp.name()
    if provider_name in QGIS_DB_PROVIDERS:
        return layer.type() == QgsMapLayerType.VectorLayer
    else:
        if provider_name == "gdal":
            # for GDAL rasters check it is a local file
            return os.path.isfile(layer.dataProvider().dataSourceUri())
        return provider_name in PACKABLE_PROVIDERS


def find_packable_layers(qgis_project=None):
    """Find layers that can be packaged for Mergin."""
    packable = []
    if qgis_project is None:
        qgis_project = QgsProject.instance()
    layers = qgis_project.mapLayers()
    for lid, layer in layers.items():
        if is_layer_packable(layer):
            packable.append(lid)
    return packable


def package_layer(layer, project_dir):
    """
    Save layer to project_dir as a single layer GPKG, unless it is already there as a GPKG layer.
    Raster layers are copied/rewritten to the project_dir depending on the their provider.
    """
    if not layer.isValid():
        raise PackagingError(f"{layer.name()} is not a valid QGIS layer")

    dp = layer.dataProvider()
    src_filepath = datasource_filepath(layer)
    if src_filepath and same_dir(os.path.dirname(src_filepath), project_dir):
        # layer already stored in the target project dir
        if layer.type() in (QgsMapLayerType.RasterLayer, QgsMapLayerType.MeshLayer):
            return True
        if layer.type() == QgsMapLayerType.VectorLayer:
            # if it is a GPKG we do not need to rewrite it
            if dp.storageType == "GPKG":
                return True

    if layer.type() == QgsMapLayerType.VectorLayer:

        fname, err = save_vector_layer_as_gpkg(layer, project_dir, update_datasource=True)
        if err:
            raise PackagingError(f"Couldn't properly save layer {layer.name()}: {err}")

    elif layer.type() == QgsMapLayerType.RasterLayer:

        save_raster_layer(layer, project_dir)

    else:
        # everything else (meshes)
        raise PackagingError("Layer type not supported")


def save_raster_layer(raster_layer, project_dir):
    """
    Save raster layer to the project directory.
    If the source raster is a local GeoTiff, create a copy of the original file in the project directory.
    Remote COG rasters are kept as they are.
    If it is a GeoPackage raster, save it also as a GeoPackage table.
    Otherwise, save the raster as GeoTiff using Qgs with some optimisations.
    """

    driver_name = get_raster_driver_name(raster_layer)

    if driver_name == "GTiff":
        # check if it is a local file
        is_local = os.path.isfile(raster_layer.dataProvider().dataSourceUri())
        if is_local:
            copy_tif_raster(raster_layer, project_dir)
    elif driver_name == "GPKG":
        save_raster_to_geopackage(raster_layer, project_dir)
    else:
        save_raster_as_geotif(raster_layer, project_dir)


def copy_tif_raster(raster_layer, project_dir):
    """Create a copy of raster layer file(s) without rewriting."""
    dp = raster_layer.dataProvider()
    src_filepath = dp.dataSourceUri() if os.path.isfile(dp.dataSourceUri()) else None
    if src_filepath is None:
        raise PackagingError(f"Can't find the source file for {raster_layer.name()}")

    # Make sure the destination path is unique and create a copy including any external pyramids
    new_raster_filename = get_unique_filename(os.path.join(project_dir, os.path.basename(src_filepath)))
    shutil.copy(src_filepath, new_raster_filename)
    # External pyramids
    if os.path.exists(src_filepath + ".ovr"):
        shutil.copy(src_filepath + ".ovr", new_raster_filename + ".ovr")
    # Erdas external pyramids
    src_filepath_no_ext = os.path.splitext(src_filepath)[0]
    if os.path.exists(src_filepath_no_ext + ".aux"):
        shutil.copy(src_filepath_no_ext + ".aux", os.path.splitext(new_raster_filename)[0] + ".aux")


def save_raster_to_geopackage(raster_layer, project_dir):
    """Save a GeoPackage raster to GeoPackage table in the project directory."""
    layer_filename = get_unique_filename(os.path.join(project_dir, raster_layer.name() + ".gpkg"))

    raster_writer = QgsRasterFileWriter(layer_filename)
    raster_writer.setOutputFormat("gpkg")
    raster_writer.setCreateOptions([f"RASTER_TABLE={raster_layer.name()}", "APPEND_SUBDATASET=YES"])

    write_raster(raster_layer, raster_writer, layer_filename)


def save_raster_as_geotif(raster_layer, project_dir):
    """Save raster layer as GeoTiff in the project directory."""
    new_raster_filename = get_unique_filename(raster_layer.name() + ".tif")
    layer_filename = os.path.join(project_dir, os.path.basename(new_raster_filename))
    # Get data type info to set a proper compression type
    dp = raster_layer.dataProvider()
    is_byte_data = [dp.dataType(i) <= Qgis.Byte for i in range(raster_layer.bandCount())]
    compression = "JPEG" if all(is_byte_data) else "LZW"
    writer_options = [f"COMPRESS={compression}", "TILED=YES"]

    raster_writer = QgsRasterFileWriter(layer_filename)
    raster_writer.setCreateOptions(writer_options)
    raster_writer.setBuildPyramidsFlag(QgsRaster.PyramidsFlagYes)
    raster_writer.setPyramidsFormat(QgsRaster.PyramidsInternal)
    raster_writer.setPyramidsList([2, 4, 8, 16, 32, 64, 128])
    write_raster(raster_layer, raster_writer, layer_filename)


def get_raster_driver_name(raster_layer):
    """Use GDAL module to get the raster driver short name."""
    ds = gdal.Open(raster_layer.dataProvider().dataSourceUri(), gdal.GA_ReadOnly)
    try:
        driver_name = ds.GetDriver().ShortName
    except AttributeError:
        driver_name = "Unknown"
    del ds
    return driver_name


def write_raster(raster_layer, raster_writer, write_path):
    """Write raster to specified file and update the layer's data source."""
    dp = raster_layer.dataProvider()
    pipe = QgsRasterPipe()
    if not pipe.set(dp.clone()):
        raise PackagingError(f"Couldn't set raster pipe projector for layer {write_path}")

    projector = QgsRasterProjector()
    projector.setCrs(raster_layer.crs(), raster_layer.crs())
    if not pipe.insert(2, projector):
        raise PackagingError(f"Couldn't set raster pipe provider for layer {write_path}")

    res = raster_writer.writeRaster(pipe, dp.xSize(), dp.ySize(), dp.extent(), raster_layer.crs())
    if not res == QgsRasterFileWriter.NoError:
        raise PackagingError(f"Couldn't save raster {write_path} - write error: {res}")

    provider_opts = QgsDataProvider.ProviderOptions()
    provider_opts.layerName = raster_layer.name()
    raster_layer.setDataSource(write_path, raster_layer.name(), "gdal", provider_opts)


def login_error_message(e):
    QgsApplication.messageLog().logMessage(f"Mergin plugin: {str(e)}")
    msg = "<font color=red>Security token has been expired, failed to renew. Check your username and password </font>"
    QMessageBox.critical(None, "Login failed", msg, QMessageBox.Close)


def unhandled_exception_message(error_details, dialog_title, error_text):
    msg = (
        error_text + "<p>This should not happen, "
        '<a href="https://github.com/lutraconsulting/qgis-mergin-plugin/issues">'
        "please report the problem</a>."
    )
    box = QMessageBox()
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle(dialog_title)
    box.setText(msg)
    box.setDetailedText(error_details)
    box.exec_()


def write_project_variables(project_owner, project_name, project_full_name, version, server):
    QgsExpressionContextUtils.setProjectVariable(QgsProject.instance(), "mergin_project_name", project_name)
    QgsExpressionContextUtils.setProjectVariable(QgsProject.instance(), "mergin_project_owner", project_owner)
    QgsExpressionContextUtils.setProjectVariable(QgsProject.instance(), "mergin_project_full_name", project_full_name)
    QgsExpressionContextUtils.setProjectVariable(QgsProject.instance(), "mergin_project_version", int_version(version))
    QgsExpressionContextUtils.setProjectVariable(QgsProject.instance(), "mergin_project_server", server)


def remove_project_variables():
    QgsExpressionContextUtils.removeProjectVariable(QgsProject.instance(), "mergin_project_name")
    QgsExpressionContextUtils.removeProjectVariable(QgsProject.instance(), "mergin_project_full_name")
    QgsExpressionContextUtils.removeProjectVariable(QgsProject.instance(), "mergin_project_version")
    QgsExpressionContextUtils.removeProjectVariable(QgsProject.instance(), "mergin_project_owner")
    QgsExpressionContextUtils.removeProjectVariable(QgsProject.instance(), "mergin_project_server")


def pretty_summary(summary):
    msg = ""
    for k, v in summary.items():
        msg += "\nDetails " + k
        msg += "".join(
            "\n layer name - "
            + d["table"]
            + ": inserted: "
            + str(d["insert"])
            + ", modified: "
            + str(d["update"])
            + ", deleted: "
            + str(d["delete"])
            for d in v["geodiff_summary"]
            if d["table"] != "gpkg_contents"
        )
    return msg


def get_local_mergin_projects_info():
    """Get a list of local Mergin projects info from QSettings."""
    local_projects_info = []
    settings = QSettings()
    config_server = settings.value("Mergin/server", None)
    if config_server is None:
        return local_projects_info
    settings.beginGroup("Mergin/localProjects/")
    for key in settings.allKeys():
        # Expecting key in the following form: '<namespace>/<project_name>/path'
        # - needs project dir to load metadata
        key_parts = key.split("/")
        if len(key_parts) > 2 and key_parts[2] == "path":
            local_path = settings.value(key, None)
            # double check if the path exists - it might get deleted manually
            if local_path is None or not os.path.exists(local_path):
                continue
            # We also need the server the project was created for, but users may already have some projects created
            # without the server specified. In that case, let's assume it is currently defined server and also store
            # the info for later, when user will be able to change server config actively.
            server_key = f"{key_parts[0]}/{key_parts[1]}/server"
            proj_server = settings.value(server_key, None)
            if proj_server is None:
                proj_server = config_server
                settings.setValue(server_key, config_server)
            # project info = (path, project owner, project name, server)
            local_projects_info.append((local_path, key_parts[0], key_parts[1], proj_server))
    return local_projects_info


def set_qgis_project_mergin_variables():
    """Check if current QGIS project is a local Mergin project and set QGIS project variables for Mergin."""
    qgis_project_path = QgsProject.instance().absolutePath()
    if not qgis_project_path:
        return None
    for local_path, owner, name, server in get_local_mergin_projects_info():
        if same_dir(path, qgis_project_path):
            try:
                mp = MerginProject(path)
                metadata = mp.metadata
                write_project_variables(
                    owner, name, metadata.get("name"), metadata.get("version"), server
                )
                return metadata.get("name")
            except InvalidProject:
                remove_project_variables()
    return None


def mergin_project_local_path(project_name=None):
    """
    Try to get local Mergin project path. If project_name is specified, look for this specific project, otherwise
    check if current QGIS project directory is listed in QSettings Mergin local projects list.
    :return: Mergin project local path if project was already downloaded, None otherwise.
    """
    settings = QSettings()
    if project_name is not None:
        proj_path = settings.value(f"Mergin/localProjects/{project_name}/path", None)
        # check local project dir was not unintentionally removed, or .mergin dir was removed
        if proj_path:
            if not os.path.exists(proj_path) or not check_mergin_subdirs(proj_path):
                # project dir does not exist or is not a Mergin project anymore, let's remove it from settings
                settings.remove(f"Mergin/localProjects/{project_name}/path")
                proj_path = None
        return proj_path

    qgis_project_path = QgsProject.instance().absolutePath()
    if not qgis_project_path:
        return None

    for local_path, owner, name, server in get_local_mergin_projects_info():
        if same_dir(local_path, qgis_project_path):
            return qgis_project_path

    return None


def icon_path(icon_filename, fa_icon=True):
    if fa_icon:
        ipath = os.path.join(os.path.dirname(os.path.realpath(__file__)), "images", "FA_icons", icon_filename)
    else:
        ipath = os.path.join(os.path.dirname(os.path.realpath(__file__)), "images", icon_filename)
    return ipath


def check_mergin_subdirs(directory):
    """Check if the directory has a Mergin project subdir (.mergin)."""
    for root, dirs, files in os.walk(directory):
        for name in dirs:
            if name == ".mergin":
                return os.path.join(root, name)
    return False


def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False
    except TypeError:
        return False
