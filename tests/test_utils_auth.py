# -*- coding: utf-8 -*-

# GPLv3 license
# Copyright Lutra Consulting Limited

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from Mergin import utils_auth


def patch_auth_manager(monkeypatch, auth_manager):
    monkeypatch.setattr(
        utils_auth, "QgsApplication", SimpleNamespace(authManager=lambda: auth_manager)
    )


def test_get_mergin_auth_cfg_reports_unavailable_auth_manager(monkeypatch):
    monkeypatch.setattr(utils_auth, "get_authcfg", lambda: "auth-id")
    patch_auth_manager(monkeypatch, None)

    with pytest.raises(
        utils_auth.MissingAuthConfigError,
        match="QGIS authentication manager is not available",
    ):
        utils_auth.get_mergin_auth_cfg()


def test_get_mergin_auth_cfg_reports_disabled_auth_manager(monkeypatch):
    monkeypatch.setattr(utils_auth, "get_authcfg", lambda: "auth-id")
    auth_manager = MagicMock()
    auth_manager.isDisabled.return_value = True
    patch_auth_manager(monkeypatch, auth_manager)

    with pytest.raises(
        utils_auth.MissingAuthConfigError,
        match="QGIS authentication manager is not available",
    ):
        utils_auth.get_mergin_auth_cfg()


def test_get_mergin_auth_cfg_reports_missing_stored_config(monkeypatch):
    monkeypatch.setattr(utils_auth, "get_authcfg", lambda: "auth-id")
    auth_manager = MagicMock()
    auth_manager.isDisabled.return_value = False
    auth_manager.loadAuthenticationConfig.return_value = False
    patch_auth_manager(monkeypatch, auth_manager)

    with pytest.raises(
        utils_auth.MissingAuthConfigError,
        match="credentials could not be saved",
    ):
        utils_auth.get_mergin_auth_cfg()


def test_store_mergin_authcfg_id_does_not_persist_failed_store(monkeypatch):
    auth_manager = MagicMock()
    auth_manager.isDisabled.return_value = False
    cfg = MagicMock()
    cfg.id.return_value = ""
    auth_manager.storeAuthenticationConfig.return_value = (False, cfg)
    patch_auth_manager(monkeypatch, auth_manager)

    settings = MagicMock()
    monkeypatch.setattr(utils_auth, "QSettings", lambda: settings)

    with pytest.raises(utils_auth.MissingAuthConfigError):
        utils_auth.store_mergin_authcfg_id(cfg)

    settings.setValue.assert_not_called()


def test_store_mergin_authcfg_id_persists_successful_update(monkeypatch):
    auth_manager = MagicMock()
    auth_manager.isDisabled.return_value = False
    auth_manager.updateAuthenticationConfig.return_value = True
    cfg = MagicMock()
    cfg.id.return_value = "auth-id"
    patch_auth_manager(monkeypatch, auth_manager)

    settings = MagicMock()
    monkeypatch.setattr(utils_auth, "QSettings", lambda: settings)

    utils_auth.store_mergin_authcfg_id(cfg)

    auth_manager.updateAuthenticationConfig.assert_called_once_with(cfg)
    settings.setValue.assert_called_once_with("Mergin/authcfg", "auth-id")
