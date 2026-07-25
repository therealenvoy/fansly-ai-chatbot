"""Tests for FanslyClient — response parsing, error handling, URL construction.

TDD: Write test (RED) → implement (GREEN) → refactor.
"""
import pytest
import httpx
from unittest.mock import MagicMock

from src.fansly_client import (
    ApifanslyClient as FanslyClient, FanslyConfig, ResponseParser,
    FanslyClientError, PaymentRequiredError, NotFoundError, AuthError,
    ChatInfo, MessageInfo, SentMessage,
)


def _make_httpx_error(status_code: int, text: str = "", headers: dict | None = None) -> MagicMock:
    """Create a mock httpx.Response that raises HTTPStatusError on raise_for_status()."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.headers = headers or {}
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        f"{status_code} {text}",
        request=MagicMock(spec=httpx.Request),
        response=resp,
    )
    return resp


def _make_httpx_success(data: dict) -> MagicMock:
    """Create a mock httpx.Response for a successful (200) response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = data
    return resp


# ─── ResponseParser Tests ───────────────────────────────────

class TestResponseParser:
    """Validate API response structure extraction."""

    def test_parse_standard_response(self):
        """Happy path: extract response key from nested API shape."""
        data = {"data": {"data": {"response": [{"id": "1"}]}}}
        result = ResponseParser.parse(data)
        assert result == [{"id": "1"}]

    def test_parse_missing_key_returns_default(self):
        """Missing path key returns None by default."""
        data = {"data": {"data": {}}}
        result = ResponseParser.parse(data, path="nonexistent")
        assert result is None

    def test_parse_with_custom_default(self):
        """Custom default value when path is missing."""
        data = {"data": {"data": {}}}
        result = ResponseParser.parse(data, path="response", default=[])
        assert result == []

    def test_parse_malformed_response_raises_valueerror(self):
        """None input raises ValueError."""
        with pytest.raises(ValueError):
            ResponseParser.parse(None)

    def test_parse_empty_dict_returns_default(self):
        """Empty dict gracefully returns None (no crash)."""
        result = ResponseParser.parse({})
        assert result is None

    def test_parse_no_data_key_returns_default(self):
        """Missing 'data' key returns default."""
        data = {"statusCode": 200}
        result = ResponseParser.parse(data, default="fallback")
        assert result == "fallback"

    def test_parse_path_none_returns_inner(self):
        """path=None returns the full inner data dict."""
        data = {"data": {"data": {"response": [1], "extra": "info"}}}
        result = ResponseParser.parse(data, path=None)
        assert result == {"response": [1], "extra": "info"}

    def test_get_cursor_present(self):
        """Extract pagination cursor."""
        data = {"data": {"nextCursor": "abc123", "data": {"response": []}}}
        assert ResponseParser.get_cursor(data) == "abc123"

    def test_get_cursor_missing(self):
        """Missing cursor returns None."""
        data = {"data": {"data": {"response": []}}}
        assert ResponseParser.get_cursor(data) is None

    def test_get_cursor_no_data_key(self):
        """Missing 'data' key entirely returns None."""
        data = {}
        assert ResponseParser.get_cursor(data) is None


# ─── Error Categorization Tests ────────────────────────────

class TestErrorCategorization:
    """Validate that _request correctly categorizes HTTP errors."""

    def _make_client(self, mock_response, max_retries=2, retry_delay=0.01):
        """Create a FanslyClient whose _client returns mock_response on request()."""
        config = FanslyConfig(
            api_key="test", account_id="test",
            max_retries=max_retries, retry_delay=retry_delay,
        )
        client = FanslyClient(config)
        mock_httpx = MagicMock(spec=httpx.Client)
        mock_httpx.request.return_value = mock_response
        client._client = mock_httpx
        return client, mock_httpx

    def test_401_raises_auth_error(self):
        """401 status -> AuthError."""
        client, _ = self._make_client(_make_httpx_error(401, "Unauthorized"))
        with pytest.raises(AuthError):
            client._request("GET", "/test")

    def test_403_raises_auth_error(self):
        """403 status -> AuthError."""
        client, _ = self._make_client(_make_httpx_error(403, "Forbidden"))
        with pytest.raises(AuthError):
            client._request("GET", "/test")

    def test_402_raises_payment_required_error(self):
        """402 status -> PaymentRequiredError."""
        client, _ = self._make_client(_make_httpx_error(402, "Payment Required"))
        with pytest.raises(PaymentRequiredError):
            client._request("GET", "/test")

    def test_404_raises_not_found_error(self):
        """404 status -> NotFoundError."""
        client, _ = self._make_client(_make_httpx_error(404, "Not Found"))
        with pytest.raises(NotFoundError):
            client._request("GET", "/test")

    def test_api_level_401_in_body_raises_auth_error(self):
        """API-level error (statusCode in body) raises AuthError."""
        resp = _make_httpx_success({"statusCode": 401, "message": "Token expired"})
        client, _ = self._make_client(resp)
        with pytest.raises(AuthError):
            client._request("GET", "/test")

    def test_api_level_402_in_body_raises_payment_error(self):
        """API-level statusCode 402 raises PaymentRequiredError."""
        resp = _make_httpx_success({"statusCode": 402, "message": "Invoice due"})
        client, _ = self._make_client(resp)
        with pytest.raises(PaymentRequiredError):
            client._request("GET", "/test")

    def test_429_retries_then_succeeds(self):
        """429 triggers retry, then succeeds on second attempt."""
        retry = _make_httpx_error(429, "Too Many Requests", {"Retry-After": "0"})
        success = _make_httpx_success({"data": {"data": {"response": "ok"}}})
        client, mock_httpx = self._make_client(retry, max_retries=3)
        mock_httpx.request.side_effect = [retry, success]
        result = client._request("GET", "/test")
        assert result == {"data": {"data": {"response": "ok"}}}
        assert mock_httpx.request.call_count == 2

    def test_429_retries_exhausted_raises(self):
        """429 repeated -> raise Exception after max_retries exhausted."""
        retry = _make_httpx_error(429, "Too Many Requests", {"Retry-After": "0"})
        client, _ = self._make_client(retry, max_retries=2)
        with pytest.raises(Exception, match="Request failed after 2 attempts"):
            client._request("GET", "/test")

    def test_500_retries_then_raises(self):
        """500 server error retries, then raises Exception after exhaustion."""
        err = _make_httpx_error(500, "Server Error")
        client, mock_httpx = self._make_client(err, max_retries=2)
        with pytest.raises(Exception, match="Request failed after 2 attempts"):
            client._request("GET", "/test")
        assert mock_httpx.request.call_count == 2

    def test_500_retries_then_succeeds(self):
        """500 error, then succeeds on second attempt."""
        err = _make_httpx_error(500, "Server Error")
        success = _make_httpx_success({"data": {"data": {"response": "ok"}}})
        client, mock_httpx = self._make_client(err, max_retries=3)
        mock_httpx.request.side_effect = [err, success]
        result = client._request("GET", "/test")
        assert result == {"data": {"data": {"response": "ok"}}}
        assert mock_httpx.request.call_count == 2

    def test_auth_error_not_retried(self):
        """AuthError is re-raised immediately, no retry."""
        client, mock_httpx = self._make_client(
            _make_httpx_error(401, "Unauthorized"), max_retries=3,
        )
        with pytest.raises(AuthError):
            client._request("GET", "/test")
        assert mock_httpx.request.call_count == 1

    def test_timeout_retries_then_raises(self):
        """TimeoutException retries, then re-raises after exhaustion."""
        client, mock_httpx = self._make_client(
            MagicMock(spec=httpx.Response), max_retries=2,
        )
        mock_httpx.request.side_effect = httpx.TimeoutException("Timed out")
        with pytest.raises(httpx.TimeoutException):
            client._request("GET", "/test")
        assert mock_httpx.request.call_count == 2

    def test_timeout_retries_then_succeeds(self):
        """Timeout, then success on second attempt."""
        success = _make_httpx_success({"data": {"data": {"response": "ok"}}})
        client, mock_httpx = self._make_client(
            MagicMock(spec=httpx.Response), max_retries=3,
        )
        mock_httpx.request.side_effect = [httpx.TimeoutException("Timed out"), success]
        result = client._request("GET", "/test")
        assert result == {"data": {"data": {"response": "ok"}}}
        assert mock_httpx.request.call_count == 2


# ─── ResponseParser Integration Tests ──────────────────────

class TestClientUsesResponseParser:
    """Verify that FanslyClient methods use ResponseParser instead of raw dict access."""

    def _make_client(self, api_data):
        config = FanslyConfig(
            api_key="test_key", account_id="test_account", max_retries=1,
        )
        client = FanslyClient(config)
        mock_httpx = MagicMock(spec=httpx.Client)
        mock_resp = _make_httpx_success(api_data)
        mock_httpx.request.return_value = mock_resp
        client._client = mock_httpx
        return client

    def test_list_chats_uses_response_parser(self):
        api_data = {
            "data": {
                "data": {
                    "response": {
                        "data": [{
                            "groupId": "chat_1",
                            "partnerAccountId": "acc_1",
                            "partnerUsername": "fan1",
                            "unreadCount": 2,
                        }],
                        "aggregationData": {"accounts": []},
                    }
                },
                "nextCursor": None,
            }
        }
        client = self._make_client(api_data)
        chats, cursor = client.list_chats()
        assert len(chats) == 1
        assert chats[0].chat_id == "chat_1"
        assert cursor is None

    def test_list_messages_uses_response_parser(self):
        api_data = {
            "data": {
                "data": {
                    "response": {
                        "messages": [{
                            "id": "msg_1",
                            "content": "Hello",
                            "senderId": "fan1",
                            "createdAt": 1000,
                        }],
                        "cursor": None,
                    }
                }
            }
        }
        client = self._make_client(api_data)
        messages, cursor = client.list_messages("chat_1")
        assert len(messages) == 1
        assert messages[0].message_id == "msg_1"
        assert messages[0].content == "Hello"

    def test_send_message_uses_response_parser(self):
        api_data = {
            "data": {
                "data": {
                    "response": {
                        "id": "msg_out_1",
                        "content": "Hey!",
                        "createdAt": 2000,
                    }
                }
            }
        }
        client = self._make_client(api_data)
        result = client.send_message("chat_1", "Hey!")
        assert result.message_id == "msg_out_1"
        assert result.content == "Hey!"
        assert result.success is True

    def test_get_earnings_uses_response_parser(self):
        api_data = {"data": {"data": {"response": {"balance": 100.0}}}}
        client = self._make_client(api_data)
        result = client.get_earnings()
        assert result == {"balance": 100.0}

    def test_list_albums_uses_response_parser(self):
        api_data = {
            "data": {
                "data": {
                    "response": {"albums": [{"id": "alb_1", "name": "Vault"}]}
                }
            }
        }
        client = self._make_client(api_data)
        result = client.list_albums()
        assert len(result) == 1
        assert result[0]["id"] == "alb_1"

    def test_get_profile_stats_uses_response_parser(self):
        api_data = {"data": {"data": {"response": {"views": 42}}}}
        client = self._make_client(api_data)
        result = client.get_profile_stats()
        assert result == {"views": 42}

    def test_get_fan_earnings_uses_response_parser(self):
        api_data = {
            "data": {"data": {"response": [{"month": "2024-01", "amount": 50}]}}
        }
        client = self._make_client(api_data)
        result = client.get_fan_earnings("fan_1")
        assert len(result) == 1
        assert result[0]["amount"] == 50

    def test_get_album_media_uses_response_parser(self):
        api_data = {
            "data": {
                "data": {
                    "response": [
                        {"id": "media_1", "url": "https://cdn.example.com/img.jpg"}
                    ],
                    "cursor": "next_page",
                }
            }
        }
        client = self._make_client(api_data)
        result, cursor = client.get_album_media("alb_1")
        assert len(result) == 1
        assert result[0]["id"] == "media_1"
        assert cursor == "next_page"


# ─── Exception Hierarchy Tests ────────────────────────────

class TestExceptionHierarchy:
    """Verify exception inheritance and isinstance checks."""

    def test_payment_required_is_fansly_client_error(self):
        assert issubclass(PaymentRequiredError, FanslyClientError)

    def test_not_found_is_fansly_client_error(self):
        assert issubclass(NotFoundError, FanslyClientError)

    def test_auth_error_is_fansly_client_error(self):
        assert issubclass(AuthError, FanslyClientError)

    def test_fansly_client_error_is_exception(self):
        assert issubclass(FanslyClientError, Exception)


# ─── ABC Contract Tests ─────────────────────────────────────

class TestFanslyApiClientABC:
    """The abstract interface cannot be instantiated; ApifanslyClient implements it fully."""

    def test_abc_cannot_be_instantiated(self):
        from src.fansly_client import FanslyApiClient
        with pytest.raises(TypeError):
            FanslyApiClient()

    def test_apifansly_client_is_a_fansly_api_client(self):
        from src.fansly_client import ApifanslyClient, FanslyApiClient, FanslyConfig
        config = FanslyConfig(api_key="k", account_id="a")
        client = ApifanslyClient(config)
        assert isinstance(client, FanslyApiClient)

    def test_apifansly_account_id_property(self):
        from src.fansly_client import ApifanslyClient, FanslyConfig
        config = FanslyConfig(api_key="k", account_id="acct_789")
        client = ApifanslyClient(config)
        assert client.account_id == "acct_789"

    def test_apifansly_verify_auth_success(self):
        from src.fansly_client import ApifanslyClient, FanslyConfig
        config = FanslyConfig(api_key="k", account_id="a")
        client = ApifanslyClient(config)
        client._request = MagicMock(return_value={"statusCode": 200, "data": {"data": {"response": []}}})
        assert client.verify_auth() is True
        client._request.assert_called_once_with("GET", "/a/chats", params={"limit": 1})

    def test_apifansly_verify_auth_raises_on_auth_error(self):
        from src.fansly_client import ApifanslyClient, FanslyConfig, AuthError
        config = FanslyConfig(api_key="k", account_id="a")
        client = ApifanslyClient(config)
        client._request = MagicMock(side_effect=AuthError("bad key"))
        with pytest.raises(AuthError):
            client.verify_auth()