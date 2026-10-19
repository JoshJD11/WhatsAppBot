import sys
from types import ModuleType, SimpleNamespace

from bot.excel_store import DRIVE_SCOPES, XLSX_MIME_TYPE, DriveExcelStore, LocalExcelStore


def test_local_store_round_trip(tmp_path):
    path = tmp_path / "bot.xlsx"
    path.write_bytes(b"one")
    store = LocalExcelStore(str(path))
    assert store.download() == b"one"
    store.upload(b"two")
    assert path.read_bytes() == b"two"
    assert not path.with_suffix(".tmp").exists()


def test_drive_store_uses_service_account_and_file_id(monkeypatch):
    calls = {}

    class FakeFiles:
        def get_media(self, **kwargs):
            calls["get_media"] = kwargs
            return "media-request"

        def update(self, **kwargs):
            calls["update"] = kwargs
            return SimpleNamespace(execute=lambda: {"id": kwargs["fileId"]})

    class FakeDownloader:
        def __init__(self, buffer, request):
            self.buffer = buffer

        def next_chunk(self):
            self.buffer.write(b"xlsx-bytes")
            return None, True

    class FakeUpload:
        def __init__(self, stream, mimetype, resumable):
            calls["mimetype"] = mimetype
            self.data = stream.read()

    def fake_credentials(path, scopes):
        calls["credentials"] = (path, scopes)
        return "creds"

    def fake_build(name, version, credentials, cache_discovery):
        calls["build"] = (name, version, credentials)
        return SimpleNamespace(files=lambda: FakeFiles())

    monkeypatch.setattr(
        "google.oauth2.service_account.Credentials.from_service_account_file", fake_credentials
    )
    monkeypatch.setattr("googleapiclient.discovery.build", fake_build)
    monkeypatch.setattr("googleapiclient.http.MediaIoBaseDownload", FakeDownloader)
    monkeypatch.setattr("googleapiclient.http.MediaIoBaseUpload", FakeUpload)

    store = DriveExcelStore("file-1", "/secret/sa.json")
    assert store.download() == b"xlsx-bytes"
    store.upload(b"new")

    assert calls["credentials"] == ("/secret/sa.json", DRIVE_SCOPES)
    assert calls["build"] == ("drive", "v3", "creds")
    assert calls["get_media"] == {"fileId": "file-1", "supportsAllDrives": True}
    assert calls["update"]["fileId"] == "file-1"
    assert calls["update"]["media_body"].data == b"new"
    assert calls["mimetype"] == XLSX_MIME_TYPE
