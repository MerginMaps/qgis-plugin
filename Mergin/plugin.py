# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited

import sip
import os
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsApplication,
    QgsDataItem,
    QgsLayerItem,
    QgsDataCollectionItem,
    QgsErrorItem,
    QgsDataItemProvider,
    QgsDataProvider
)
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtCore import QSettings


from urllib.error import URLError
from .configuration_dialog import ConfigurationDialog

from .client import MerginClient
from .utils import auth_ok

this_dir = os.path.dirname(__file__)


class MerginPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.data_item_provider = None
        self.actions = []
        self.menu = u'Mergin Plugin'

    def initGui(self):
        self.data_item_provider = DataItemProvider()
        QgsApplication.instance().dataItemProviderRegistry().addProvider(self.data_item_provider)

    def unload(self):
        QgsApplication.instance().dataItemProviderRegistry().removeProvider(self.data_item_provider)
        self.data_item_provider = None


class MerginProjectItem(QgsDataItem):
    """ Data item to represent a Mergin project. """

    def __init__(self, parent, project_name):
        QgsDataItem.__init__(self, QgsDataItem.Collection, parent, project_name, "/Mergin/" + project_name)
        self.repo_name = project_name
        # TODO get some fancy icon
        self.setIcon(QgsLayerItem.iconDefault())


class MerginRootItem(QgsDataCollectionItem):
    """ Mergin root data item with configuration dialog. """

    def __init__(self):
        QgsDataCollectionItem.__init__(self, None, "Mergin", "/Mergin")
        self.setIcon(QIcon(os.path.join(os.path.dirname(os.path.realpath(__file__)), "images/icon.png")))

    def createChildren(self):
        settings = QSettings()
        url = settings.value('Mergin/URL', 'https://public.cloudmergin.com')
        # TODO replace with something safer
        username = settings.value('Mergin/username', '')
        password = settings.value('Mergin/password', '')

        if not auth_ok(url, username, password):
            error_item = QgsErrorItem(self, "Failed to get projects from server", "/Mergin/error")
            sip.transferto(error_item, self)
            return [error_item]

        mc = MerginClient(url, username, password)
        try:
            projects = mc.projects_list()
        except URLError:
            error_item = QgsErrorItem(self, "Failed to get projects from server", "/Mergin/error")
            sip.transferto(error_item, self)
            return [error_item]
        except Exception as err:
            error_item = QgsErrorItem(self, "Error: {}".format(str(err)), "/Mergin/error")
            sip.transferto(error_item, self)
            return [error_item]

        items = []
        for project in projects:
            item = MerginProjectItem(self, project['name'])
            item.setState(QgsDataItem.Populated)  # make it non-expandable
            sip.transferto(item, self)
            items.append(item)
        return items

    def configure(self):
        dlg = ConfigurationDialog()
        if dlg.exec_():
            dlg.writeSettings()

    def actions(self, parent):
        action_configure = QAction("Configure", parent)
        action_configure.triggered.connect(self.configure)

        action_refresh = QAction("Reload", parent)
        action_refresh.triggered.connect(self.refresh)
        return [action_configure, action_refresh]


class DataItemProvider(QgsDataItemProvider):

    def __init__(self):
        QgsDataItemProvider.__init__(self)

    def name(self):
        return "MerginProvider"

    def capabilities(self):
        return QgsDataProvider.Net

    def createDataItem(self, path, parentItem):
        if not parentItem:
            ri = MerginRootItem()
            sip.transferto(ri, None)
            return ri
        else:
            return None

