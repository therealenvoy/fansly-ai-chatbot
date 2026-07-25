"""Tests for FanslyClient upload URL fix and file validation (Tasks 5 & 6).

C4 Bug: Upload status URL missing account_id — currently uses /media/upload/{job_id}/status
R3 Issue: No file validation before upload — should check exists, extension, size.

RED phase: Write failing tests first, then implement in fansly_client.py.
GREEN phase: All tests pass after implementation.
"""
import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from src.fansly_client import (
    ApifanslyClient as FanslyClient, FanslyConfig,
)


# ─── Helpers ─────────────────────────────────────────────────────


def _successful_status_response(media_id="mid"):
    """Create a mock response that _request returns for a completed upload.

    _request returns the full JSON body. The code does:
      status_data.get("data", {}).get("state")
    So state must be directly inside data.
    """
    return {"data": {"state": "completed", "result": {"mediaId": media_id}}}


@pytest.fixture(autouse=True)
def fast_time():
    """Make time.sleep a no-op so tests don't block on upload polling."""
    with patch("time.sleep"):
        yield


@pytest.fixture
def client():
    """Create a FanslyClient with mocked HTTP."""
    config = FanslyConfig(
        api_key="test_key",
        account_id="test_acc_123",
    )
    client = FanslyClient(config)
    client._client = MagicMock()
    return client


@pytest.fixture
def temp_image():
    """Create a temporary valid-looking image file (small .png)."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"fake_png_content")
        path = f.name
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def temp_video():
    """Create a temporary valid-looking video file (small .mp4)."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"fake_mp4_content")
        path = f.name
    yield path
    if os.path.exists(path):
        os.unlink(path)


# ══════════════════════════════════════════════════════════════════
# RED Phase — Tests for Upload URL Fix (Task 5)
# ══════════════════════════════════════════════════════════════════


class TestUploadStatusURL:
    """Verify upload status URL includes account_id."""

    def test_upload_status_url_includes_account_id(self, client, temp_image):
        """The status polling URL must include account_id."""
        # Mock the initial upload POST response
        mock_post_resp = MagicMock()
        mock_post_resp.json.return_value = {
            "data": {"jobId": "job_abc123"}
        }
        mock_post_resp.status_code = 200

        with patch("httpx.post", return_value=mock_post_resp):
            captured_paths = []

            def capturing_request(method, path, **kwargs):
                captured_paths.append(path)
                return _successful_status_response("media_xyz")

            client._request = capturing_request

            result = client.upload_media(temp_image)

            assert result == "media_xyz"
            # At least one status path should exist
            assert len(captured_paths) > 0, "Status path was never called"
            for path in captured_paths:
                assert "test_acc_123" in path, \
                    f"Status path '{path}' missing account_id"

    def test_upload_status_url_not_old_format(self, client, temp_image):
        """Status URL should NOT use the old format /media/upload/{job_id}/status."""
        mock_post_resp = MagicMock()
        mock_post_resp.json.return_value = {
            "data": {"jobId": "job_abc123"}
        }
        mock_post_resp.status_code = 200

        with patch("httpx.post", return_value=mock_post_resp):
            captured_paths = []

            def capturing_request(method, path, **kwargs):
                captured_paths.append(path)
                return _successful_status_response()

            client._request = capturing_request
            client.upload_media(temp_image)

            # No status path should start with "/media/upload/" (missing account_id)
            for path in captured_paths:
                assert not path.startswith("/media/upload/"), \
                    f"Path '{path}' uses old format (missing account_id)"


# ══════════════════════════════════════════════════════════════════
# RED Phase — Tests for Upload File Validation (Task 6)
# ══════════════════════════════════════════════════════════════════


class TestUploadFileExists:
    """File must exist before upload."""

    def test_file_not_found_raises_error(self, client):
        """Non-existent file path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Upload file not found"):
            client.upload_media("/tmp/nonexistent_file_xyz.png")

    def test_file_not_found_before_any_http_call(self, client):
        """Validation happens before any HTTP request is made."""
        with patch("httpx.post") as mock_post:
            with pytest.raises(FileNotFoundError):
                client.upload_media("/tmp/nonexistent_file_xyz.png")
            mock_post.assert_not_called()


class TestUploadFileExtension:
    """Only allowed extensions should be accepted."""

    def test_valid_png_passes(self, client, temp_image):
        """.png files should pass validation and proceed to upload."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"jobId": "job_1"}}
        mock_resp.status_code = 200

        with patch("httpx.post", return_value=mock_resp):
            client._request = MagicMock(return_value=_successful_status_response())
            result = client.upload_media(temp_image)
            assert result == "mid"

    def test_valid_mp4_passes(self, client, temp_video):
        """.mp4 files should pass validation and proceed to upload."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"jobId": "job_1"}}
        mock_resp.status_code = 200

        with patch("httpx.post", return_value=mock_resp):
            client._request = MagicMock(return_value=_successful_status_response())
            result = client.upload_media(temp_video)
            assert result == "mid"

    def test_invalid_extension_raises_error(self, client):
        """.pdf files should be rejected."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"fake_pdf")
            path = f.name
        try:
            with pytest.raises(ValueError, match="Unsupported file type"):
                client.upload_media(path)
        finally:
            os.unlink(path)

    def test_invalid_extension_before_any_http_call(self, client):
        """Validation for extension happens before any HTTP call."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"fake_pdf")
            path = f.name
        try:
            with patch("httpx.post") as mock_post:
                with pytest.raises(ValueError):
                    client.upload_media(path)
                mock_post.assert_not_called()
        finally:
            os.unlink(path)

    def test_no_extension_raises_error(self, client):
        """File with no extension should be rejected."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"content")
            path = f.name
        try:
            with pytest.raises(ValueError, match="Unsupported file type"):
                client.upload_media(path)
        finally:
            os.unlink(path)

    def test_uppercase_extension_accepted(self, client):
        """.PNG (uppercase) should be accepted (case-insensitive check)."""
        with tempfile.NamedTemporaryFile(suffix=".PNG", delete=False) as f:
            f.write(b"content")
            path = f.name
        try:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"data": {"jobId": "job_1"}}
            mock_resp.status_code = 200

            with patch("httpx.post", return_value=mock_resp):
                client._request = MagicMock(return_value=_successful_status_response())
                client.upload_media(path)
        finally:
            os.unlink(path)


class TestUploadFileSize:
    """File must not exceed MAX_UPLOAD_SIZE (500MB)."""

    def test_oversized_file_raises_error(self, client):
        """File larger than 500MB should be rejected."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"x")
            f.flush()
            os.ftruncate(f.fileno(), 501 * 1024 * 1024)  # 501MB sparse file
            path = f.name
        try:
            with pytest.raises(ValueError, match="File too large"):
                client.upload_media(path)
        finally:
            os.unlink(path)

    def test_oversized_before_any_http_call(self, client):
        """File size validation happens before any HTTP call."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"x")
            f.flush()
            os.ftruncate(f.fileno(), 501 * 1024 * 1024)
            path = f.name
        try:
            with patch("httpx.post") as mock_post:
                with pytest.raises(ValueError):
                    client.upload_media(path)
                mock_post.assert_not_called()
        finally:
            os.unlink(path)

    def test_file_at_max_size_passes(self, client):
        """File exactly at 500MB should pass validation."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"x")
            f.flush()
            os.ftruncate(f.fileno(), 500 * 1024 * 1024)  # Exactly 500MB sparse file
            path = f.name
        try:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"data": {"jobId": "job_1"}}
            mock_resp.status_code = 200

            with patch("httpx.post", return_value=mock_resp):
                client._request = MagicMock(return_value=_successful_status_response())
                client.upload_media(path)
        finally:
            os.unlink(path)