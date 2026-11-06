"""Offline OAuth/Drive protocol checks. No Google account or hardware is used."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from urllib.parse import parse_qs, urlsplit

import pytest

from src.api.dataset_capture.drive import (
    AUTH_URL, DRIVE_URL, SCOPE, TOKEN_URL, DriveHTTPError, GoogleDriveClient,
    GoogleHTTP, OAuthManager, PrivateTokenStore,
)


class OAuthHTTP:
    def __init__(self):
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return 200, {}, {"access_token": "synthetic-access-token", "refresh_token": "synthetic-refresh-token", "scope": SCOPE, "expires_in": 3600}


@pytest.fixture
def oauth(tmp_path):
    client = tmp_path / "desktop-client.json"
    client.write_text(json.dumps({"installed": {"client_id": "synthetic.apps.googleusercontent.com", "client_secret": "synthetic-test-client"}}))
    manager = OAuthManager(tmp_path / "private", client_file=client, http=OAuthHTTP(), clock=lambda: 1000)
    yield manager
    manager.close()


def test_oauth_missing_client_is_honest_and_no_network(tmp_path):
    manager = OAuthManager(tmp_path, http=OAuthHTTP())
    assert not manager.status()["oauth_configured"]
    with pytest.raises(DriveHTTPError, match="FISH_CAPTURE_OAUTH_CLIENT_FILE"):
        manager.start_authorization()
    assert not manager.http.requests


def test_pkce_uses_loopback_state_and_keeps_tokens_off_authorization_url(oauth):
    response = oauth.start_authorization()
    url = urlsplit(response["authorization_url"])
    query = parse_qs(url.query)
    assert response["authorization_url"].startswith(AUTH_URL)
    assert query["scope"] == [SCOPE]
    assert query["code_challenge_method"] == ["S256"]
    redirect = urlsplit(query["redirect_uri"][0])
    assert redirect.hostname == "127.0.0.1" and redirect.port > 0
    verifier = oauth._pending["verifier"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [challenge]
    assert verifier not in response["authorization_url"]
    assert "client_secret" not in query and "access_token" not in query
    with pytest.raises(DriveHTTPError):
        oauth.finish_authorization("wrong-state", "synthetic-code")
    assert not oauth.http.requests
    oauth.finish_authorization(query["state"][0], "synthetic-code")
    fields = parse_qs(oauth.http.requests[0][2]["body"].decode())
    assert fields["code_verifier"] == [verifier]
    assert oauth.status()["connected"]
    assert oauth.token_store.load()["refresh_token"] == "synthetic-refresh-token"
    with pytest.raises(DriveHTTPError):
        oauth.finish_authorization(query["state"][0], "synthetic-code")


def test_consent_denial_does_not_create_tokens(oauth):
    response = oauth.start_authorization()
    state = parse_qs(urlsplit(response["authorization_url"]).query)["state"][0]
    with pytest.raises(DriveHTTPError):
        oauth.finish_authorization(state, "", "access_denied")
    assert not oauth.token_store.path.exists()
    assert not oauth.status()["connected"]


def test_expired_oauth_state_cannot_exchange(oauth):
    oauth._pending = {"state": "expected-state", "expires": 0}
    with pytest.raises(DriveHTTPError):
        oauth.finish_authorization("expected-state", "code")
    assert not oauth.http.requests


def test_refresh_is_server_only_and_persisted(oauth):
    oauth._tokens = {"refresh_token": "synthetic-refresh-token", "expires_at": 0}
    assert oauth.access_token() == "synthetic-access-token"
    assert oauth.http.requests[0][1] == TOKEN_URL
    fields = parse_qs(oauth.http.requests[0][2]["body"].decode())
    assert fields["grant_type"] == ["refresh_token"]
    status = json.dumps(oauth.status())
    assert "synthetic-refresh-token" not in status and "synthetic-access-token" not in status


def test_token_store_uses_os_protection(tmp_path):
    store = PrivateTokenStore(tmp_path / "private/token.bin")
    store.save({"refresh_token": "synthetic-private-value"})
    assert store.load() == {"refresh_token": "synthetic-private-value"}
    if os.name == "nt":
        assert b"synthetic-private-value" not in store.path.read_bytes()
    else:
        assert store.path.stat().st_mode & 0o077 == 0


class FakeOAuth:
    def access_token(self):
        return "synthetic-bearer"


class ScriptedHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        assert self.responses, (method, url)
        return 200, {}, self.responses.pop(0)


ROOT = "synthetic_root_123456"


def test_destination_capability_requires_real_folder_permission():
    http = ScriptedHTTP([{"id": ROOT, "mimeType": "application/vnd.google-apps.folder", "capabilities": {"canAddChildren": False, "canListChildren": True}}])
    client = GoogleDriveClient(FakeOAuth(), ROOT, http=http)
    with pytest.raises(DriveHTTPError) as error:
        client.test_access()
    assert error.value.status_code == 403
    assert all(r[0] == "GET" for r in http.requests)


def test_capability_detects_shared_drive_without_creating_files():
    http = ScriptedHTTP([{"id": ROOT, "name": "Synthetic", "driveId": "shared_drive_123456", "mimeType": "application/vnd.google-apps.folder", "capabilities": {"canAddChildren": True, "canListChildren": True}}])
    result = GoogleDriveClient(FakeOAuth(), ROOT, http=http).test_access()
    assert result["can_upload"] and result["drive_type"] == "shared_drive"
    assert len(http.requests) == 1 and http.requests[0][0] == "GET"


def test_idempotent_lookup_scopes_query_and_confirms_parent_and_checksum():
    digest = "a" * 64
    http = ScriptedHTTP([{"files": [{"id": "remote_file_123456", "parents": [ROOT], "sha256Checksum": digest}]}])
    client = GoogleDriveClient(FakeOAuth(), ROOT, http=http)
    assert client.find_file("image-id-123", ROOT) == {"id": "remote_file_123456", "sha256": digest, "size": None}
    query = parse_qs(urlsplit(http.requests[0][1]).query)["q"][0]
    assert "capture_root" in query and ROOT in query and "image-id-123" in query
    assert "includeItemsFromAllDrives=true" in http.requests[0][1]


@pytest.mark.parametrize("folder,key", [("wrong-root-12345", "ok-key"), (ROOT, "x' or trashed=true"), (ROOT, "../escape")])
def test_unapproved_destination_or_injected_identity_never_reaches_network(folder, key):
    http = ScriptedHTTP([])
    client = GoogleDriveClient(FakeOAuth(), ROOT, http=http)
    with pytest.raises(DriveHTTPError):
        client.find_file(key, folder)
    assert not http.requests


def test_remote_mapping_moved_outside_destination_is_refused():
    http = ScriptedHTTP([{"files": [{"id": "remote_file_123456", "parents": []}]}])
    with pytest.raises(DriveHTTPError) as error:
        GoogleDriveClient(FakeOAuth(), ROOT, http=http).find_file("image-1", ROOT)
    assert error.value.status_code == 403


def test_ambiguous_remote_identity_is_not_uploaded_again():
    http = ScriptedHTTP([{"files": [{"id": "remote_file_one"}, {"id": "remote_file_two"}]}])
    with pytest.raises(DriveHTTPError) as error:
        GoogleDriveClient(FakeOAuth(), ROOT, http=http).find_file("image-1", ROOT)
    assert error.value.status_code == 409 and len(http.requests) == 1


def test_google_http_rejects_redirect_and_non_google_api_destinations():
    for url in ("http://www.googleapis.com/drive/v3/files", "https://example.com/files", "https://user@www.googleapis.com/drive/v3/files"):
        with pytest.raises(DriveHTTPError):
            GoogleHTTP().request("GET", url)
