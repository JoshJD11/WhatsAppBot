"""Where the Excel file lives: Google Drive in production, a local file for development.

Both stores are synchronous; callers run them in a worker thread.
"""

from io import BytesIO
from pathlib import Path
from typing import Protocol

XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# Full Drive scope: a service account can only edit a file shared with it under this scope.
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


class ExcelStore(Protocol):
    def download(self) -> bytes: ...

    def upload(self, data: bytes) -> None: ...


class LocalExcelStore:
    """Reads and writes an .xlsx on disk. Useful before the Drive setup is ready."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def download(self) -> bytes:
        return self._path.read_bytes()

    def upload(self, data: bytes) -> None:
        temporary = self._path.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(self._path)


class DriveExcelStore:
    """Downloads and replaces an .xlsx file on Google Drive with a service account."""

    def __init__(self, file_id: str, service_account_file: str) -> None:
        # Imported here so tests and local mode do not need Google credentials.
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            service_account_file, scopes=DRIVE_SCOPES
        )
        self._file_id = file_id
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    def download(self) -> bytes:
        from googleapiclient.http import MediaIoBaseDownload

        request = self._service.files().get_media(fileId=self._file_id, supportsAllDrives=True)
        buffer = BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    def upload(self, data: bytes) -> None:
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(BytesIO(data), mimetype=XLSX_MIME_TYPE, resumable=False)
        self._service.files().update(
            fileId=self._file_id, media_body=media, supportsAllDrives=True
        ).execute()
