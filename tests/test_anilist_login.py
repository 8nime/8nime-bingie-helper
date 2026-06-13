# -*- coding: utf-8 -*-
"""Tests for the helper-native AniList login orchestration (QR dialog + token)."""
from resources.lib import anilist_login, api, auth


def _dialog_factory(proceed, token):
    class _Dlg:
        def __init__(self, *a, **k):
            self.proceed = proceed
            self.token = token

        def doModal(self):
            pass

    return _Dlg


class TestPromptLogin:
    def test_success_validates_and_saves(self, monkeypatch):
        monkeypatch.setattr(anilist_login, "AniListLoginDialog", _dialog_factory(True, "TKN"))
        monkeypatch.setattr(
            api, "validate_token",
            lambda t: {"id": 7, "name": "Neo"} if t == "TKN" else None,
        )
        saved = {}
        monkeypatch.setattr(auth, "set_anilist_token", lambda tok, name="": saved.update(token=tok, name=name))
        assert anilist_login.prompt_login() is True
        assert saved == {"token": "TKN", "name": "Neo"}

    def test_invalid_token_not_saved(self, monkeypatch):
        monkeypatch.setattr(anilist_login, "AniListLoginDialog", _dialog_factory(True, "BAD"))
        monkeypatch.setattr(api, "validate_token", lambda t: None)
        called = {}
        monkeypatch.setattr(auth, "set_anilist_token", lambda *a, **k: called.setdefault("saved", True))
        assert anilist_login.prompt_login() is False
        assert "saved" not in called

    def test_cancel_skips_validation_and_save(self, monkeypatch):
        monkeypatch.setattr(anilist_login, "AniListLoginDialog", _dialog_factory(False, ""))
        called = {}
        monkeypatch.setattr(api, "validate_token", lambda t: called.setdefault("validated", True))
        monkeypatch.setattr(auth, "set_anilist_token", lambda *a, **k: called.setdefault("saved", True))
        assert anilist_login.prompt_login() is False
        assert called == {}

    def test_whitespace_token_skips_validation(self, monkeypatch):
        monkeypatch.setattr(anilist_login, "AniListLoginDialog", _dialog_factory(True, "   "))
        called = {}
        monkeypatch.setattr(api, "validate_token", lambda t: called.setdefault("validated", True))
        assert anilist_login.prompt_login() is False
        assert called == {}


class TestLogout:
    def test_logout_when_logged_in(self, monkeypatch):
        monkeypatch.setattr(auth, "has_anilist_token", lambda: True)
        cleared = {}
        monkeypatch.setattr(auth, "clear_anilist_token", lambda: cleared.setdefault("done", True))
        assert anilist_login.logout() is True  # stub Dialog().yesno -> True
        assert cleared.get("done")

    def test_logout_when_not_logged_in(self, monkeypatch):
        monkeypatch.setattr(auth, "has_anilist_token", lambda: False)
        cleared = {}
        monkeypatch.setattr(auth, "clear_anilist_token", lambda: cleared.setdefault("done", True))
        assert anilist_login.logout() is False
        assert "done" not in cleared
