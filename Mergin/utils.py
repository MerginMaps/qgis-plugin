from datetime import datetime, timezone
from urllib.error import URLError, HTTPError
import configparser
import os
import pathlib
import platform
import urllib.parse
import urllib.request

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import QMessageBox, QFileDialog

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsAuthMethodConfig,
    QgsCoordinateReferenceSystem,
    QgsExpressionContextUtils,
    QgsProject,
    QgsRasterLayer,
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

MERGIN_URL = 'https://public.cloudmergin.com'
MERGIN_LOGS_URL = 'https://g4pfq226j0.execute-api.eu-west-1.amazonaws.com/mergin_client_log_submit'


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


def create_mergin_client():
    url, username, password = get_mergin_auth()
    settings = QSettings()
    auth_token = settings.value('Mergin/auth_token', None)
    if auth_token:
        mc = MerginClient(url, auth_token, username, password, get_plugin_version())
        # check token expiration
        delta = mc._auth_session['expire'] - datetime.now(timezone.utc)
        if delta.total_seconds() > 1:
            return mc

    if not (username and password):
        raise ClientError()

    try:
        mc = MerginClient(url, None, username, password, get_plugin_version())
    except (URLError, ClientError) as e:
        QgsApplication.messageLog().logMessage(str(e))
        raise
    settings.setValue('Mergin/auth_token', mc._auth_session['token'])
    return MerginClient(url, mc._auth_session['token'], username, password, get_plugin_version())


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

    params = {
        "app": "plugin-{}-{}".format(system, version),
        "username": username
    }
    url = MERGIN_LOGS_URL + "?" + urllib.parse.urlencode(params)
    header = {"content-type": "text/plain"}

    meta = "Plugin: {} \nQGIS: {} \nSystem: {} \nMergin URL: {} \nMergin user: {} \n--------------------------------\n"\
        .format(
            version,
            get_qgis_version_str(),
            system,
            mergin_url,
            username
        )

    with open(logfile, 'rb') as f:
        if os.path.getsize(logfile) > 512 * 1024:
            f.seek(-512 * 1024, os.SEEK_END)
        logs = f.read()

    payload = meta.encode() + logs
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
        mc = MerginClient(url)
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
    last_dir = settings.value("Mergin/lastUsedDownloadDir", "")
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
        msg = "There are some unsaved changes. Do you want save it before continue?"
        btn_reply = QMessageBox.warning(
            None, "Stop editing", msg, QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
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


def create_basic_qgis_project(project_path=None, project_name=None):
    """
    Create a basic QGIS project with OSM background.
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
    osm_layer = QgsRasterLayer(osm_url, "OSM", "wms")
    new_project.addMapLayer(osm_layer)
    write_success = new_project.write()
    if not write_success:
        QMessageBox.warning(None, "Error Creating New Project", f"Couldn't create new project:\n{project_path}")
        return None
    return project_path


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


def write_project_variables(project_owner, project_name, project_full_name, version):
    QgsExpressionContextUtils.setProjectVariable(QgsProject.instance(), "mergin_project_name", project_name)
    QgsExpressionContextUtils.setProjectVariable(QgsProject.instance(), "mergin_project_owner", project_owner)
    QgsExpressionContextUtils.setProjectVariable(QgsProject.instance(), "mergin_project_full_name", project_full_name)
    QgsExpressionContextUtils.setProjectVariable(QgsProject.instance(), "mergin_project_version", int_version(version))


def remove_project_variables():
    QgsExpressionContextUtils.removeProjectVariable(QgsProject.instance(), "mergin_project_name")
    QgsExpressionContextUtils.removeProjectVariable(QgsProject.instance(), "mergin_project_full_name")
    QgsExpressionContextUtils.removeProjectVariable(QgsProject.instance(), "mergin_project_version")
    QgsExpressionContextUtils.removeProjectVariable(QgsProject.instance(), "mergin_project_owner")


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
    settings.beginGroup("Mergin/localProjects/")
    for key in settings.allKeys():
        # Expecting key in the following form: '<namespace>/<project_name>/path'
        # - needs project dir to load metadata
        key_parts = key.split("/")
        if len(key_parts) > 2 and key_parts[2] == "path":
            local_path = settings.value(key)
            # double check if the path exists - it might get deleted manually
            if not os.path.exists(local_path):
                continue
            local_projects_info.append((local_path, key_parts[0], key_parts[1]))  # (path, project owner, project name)
    return local_projects_info


def set_qgis_project_mergin_variables():
    """Check if current QGIS project is a local Mergin project and set QGIS project variables for Mergin."""
    qgis_project_path = QgsProject.instance().absolutePath()
    if not qgis_project_path:
        return None
    for local_path, owner, name in get_local_mergin_projects_info():
        if same_dir(path, qgis_project_path):
            try:
                mp = MerginProject(path)
                metadata = mp.metadata
                write_project_variables(
                    owner, name, metadata.get("name"), metadata.get("version")
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
        # check local project dir was not unintentionally removed
        if proj_path:
            if not os.path.exists(proj_path):
                proj_path = None
        return proj_path

    qgis_project_path = QgsProject.instance().absolutePath()
    if not qgis_project_path:
        return None

    for local_path, owner, name in get_local_mergin_projects_info():
        if same_dir(local_path, qgis_project_path):
            return qgis_project_path

    return None
