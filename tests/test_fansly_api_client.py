"""Tests for FanslyApiClientImpl — the app.onlyfansapi.com Fansly provider.

Every mocked response body below is the REAL shape captured from
docs.onlyfansapi.com/api-reference/fansly during the design session for
this feature (2026-07-25), not invented data.
"""
import pytest
import httpx
from unittest.mock import MagicMock

from src.fansly_client import FanslyApiClient, AuthError, PaymentRequiredError
from src.fansly_api_client import FanslyApiClientImpl


def _resp(json_body: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(spec=httpx.Request), response=resp
        )
    return resp


LIST_ACCOUNTS_BODY = [
    {
        "id": "fansly_acct_123",
        "display_name": "My Fansly",
        "fansly_id": "111222333",
        "fansly_username": "tester",
        "is_authenticated": True,
        "authentication_progress": "authenticated",
    }
]

LIST_CHATS_BODY = {
    "data": {
        "data": [
            {
                "groupId": "200000000000000001",
                "partnerAccountId": "300000000000000001",
                "partnerUsername": "partner",
                "unreadCount": 1,
                "lastMessageId": "400000000000000001",
                "subscriptionTierId": None,
            }
        ],
        "aggregationData": {
            "accounts": [
                {
                    "id": "300000000000000001",
                    "username": "partner",
                    "displayName": "Partner",
                    "avatar": {"locations": [{"location": "https://cdn3.fansly.com/x.jpeg"}]},
                }
            ]
        },
        "hasMore": False,
    },
    "_pagination": {"next_page": None},
}

LIST_MESSAGES_BODY = {
    "data": {
        "messages": [
            {
                "id": "400000000000000001",
                "content": "hey",
                "groupId": "200000000000000001",
                "senderId": "300000000000000001",
                "createdAt": 1700000000,
                "attachments": [],
                "totalTipAmount": 0,
            }
        ],
        "hasMore": False,
    }
}

SEND_MESSAGE_BODY = {
    "data": {
        "type": 1,
        "attachments": [],
        "content": "Hey there!",
        "groupId": "200000000000000001",
        "senderId": "100000000000000001",
        "id": "400000000000000010",
        "createdAt": 1700000000.123,
    }
}

ADD_REACTION_BODY = {
    "data": {
        "accountId": "100000000000000001",
        "messageId": "300000000000000001",
        "type": 1,
        "groupId": "200000000000000001",
        "id": "500000000000000001",
    }
}

UPLOAD_MEDIA_BODY = {
    "prefixed_id": "fansly_media_01JR1234ABCD5678EFGH",
    "file_name": "photo.jpg",
    "media_id": "800000000000000010",
    "credits_used": 1,
}


class TestFanslyApiClientImplIsAFanslyApiClient:
    def test_is_instance_of_abc(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        assert isinstance(client, FanslyApiClient)


class TestAccountIdResolution:
    def test_empty_api_key_fails_locally_without_sending_invalid_header(self):
        client = FanslyApiClientImpl(api_key="  ")
        client.client.request = MagicMock()

        assert "authorization" not in client.client.headers
        with pytest.raises(AuthError, match="not configured"):
            client.verify_auth()
        client.client.request.assert_not_called()

    def test_verify_auth_resolves_and_caches_account_id(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client.client.request = MagicMock(return_value=_resp(LIST_ACCOUNTS_BODY))

        assert client.verify_auth() is True
        assert client.account_id == "fansly_acct_123"
        # Cached — a second access does not re-request.
        client.client.request.assert_called_once()

    def test_verify_auth_raises_auth_error_on_401(self):
        client = FanslyApiClientImpl(api_key="bad_key")
        client.client.request = MagicMock(return_value=_resp({"error": "Unauthorized"}, 401))

        with pytest.raises(AuthError):
            client.verify_auth()

    def test_account_id_access_triggers_resolution_if_not_yet_done(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client.client.request = MagicMock(return_value=_resp(LIST_ACCOUNTS_BODY))

        assert client.account_id == "fansly_acct_123"


class TestGetAllChats:
    def test_parses_chats_from_real_response_shape(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"  # pre-resolved, skip verify_auth for this test
        client.client.request = MagicMock(return_value=_resp(LIST_CHATS_BODY))

        chats = client.get_all_chats()

        assert len(chats) == 1
        assert chats[0].chat_id == "200000000000000001"
        assert chats[0].partner_account_id == "300000000000000001"
        assert chats[0].partner_display_name == "Partner"
        assert chats[0].unread_count == 1

        called_url = client.client.request.call_args[0][1]
        assert called_url == "/api/fansly/fansly_acct_123/chats"

    def test_paginates_until_has_more_is_false(self):
        """A creator with more chats than one page must not be silently truncated."""
        import copy

        page1 = copy.deepcopy(LIST_CHATS_BODY)
        page1["data"]["hasMore"] = True
        page1["data"]["data"][0]["groupId"] = "page1_chat"

        page2 = copy.deepcopy(LIST_CHATS_BODY)
        page2["data"]["hasMore"] = False
        page2["data"]["data"][0]["groupId"] = "page2_chat"

        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"
        client.client.request = MagicMock(side_effect=[_resp(page1), _resp(page2)])

        chats = client.get_all_chats()

        assert [c.chat_id for c in chats] == ["page1_chat", "page2_chat"]
        assert client.client.request.call_count == 2
        first_call_params = client.client.request.call_args_list[0].kwargs["params"]
        second_call_params = client.client.request.call_args_list[1].kwargs["params"]
        assert first_call_params == {"limit": 100, "offset": 0}
        # page1's mock body contains exactly 1 chat, so offset advances by 1 (actual
        # count returned), not by the requested page size — a short page is valid.
        assert second_call_params == {"limit": 100, "offset": 1}


class TestListMessages:
    def test_parses_messages_from_real_response_shape(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"
        client.client.request = MagicMock(return_value=_resp(LIST_MESSAGES_BODY))

        messages, cursor = client.list_messages("200000000000000001")

        assert len(messages) == 1
        assert messages[0].message_id == "400000000000000001"
        assert messages[0].content == "hey"
        assert messages[0].is_from_fan is True  # senderId != our account_id


class TestSendMessage:
    def test_sends_text_message(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"
        client.client.request = MagicMock(return_value=_resp(SEND_MESSAGE_BODY))

        result = client.send_message("200000000000000001", "Hey there!")

        assert result.success is True
        assert result.message_id == "400000000000000010"
        sent_body = client.client.request.call_args.kwargs["json"]
        assert sent_body["text"] == "Hey there!"


class TestSendPpv:
    def test_sends_ppv_with_millidollar_price(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"
        client.client.request = MagicMock(return_value=_resp(SEND_MESSAGE_BODY))

        client.send_ppv("200000000000000001", "unlock this", "fansly_media_123", price=10.0)

        sent_body = client.client.request.call_args.kwargs["json"]
        assert sent_body["mediaFiles"] == ["fansly_media_123"]
        assert sent_body["requirePurchase"] is True
        assert sent_body["price"] == 10000  # $10.00 -> 10000 millidollars

    def test_sends_ppv_with_preview(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"
        client.client.request = MagicMock(return_value=_resp(SEND_MESSAGE_BODY))

        client.send_ppv(
            "200000000000000001", "unlock", "fansly_media_123",
            price=5.0, preview_id="fansly_media_preview_1",
        )

        sent_body = client.client.request.call_args.kwargs["json"]
        assert sent_body["previews"] == {"fansly_media_123": "fansly_media_preview_1"}


class TestLikeMessage:
    def test_likes_with_heart_reaction(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"
        client.client.request = MagicMock(return_value=_resp(ADD_REACTION_BODY))

        result = client.like_message("200000000000000001", "300000000000000001")

        assert result is True
        sent_body = client.client.request.call_args.kwargs["json"]
        assert sent_body["type"] == 1


class TestUploadMedia:
    def test_uploads_via_file_url_and_returns_media_id(self, tmp_path):
        client = FanslyApiClientImpl(api_key="sk_test")
        client._account_id = "fansly_acct_123"
        client.client.request = MagicMock(return_value=_resp(UPLOAD_MEDIA_BODY))

        f = tmp_path / "photo.jpg"
        f.write_bytes(b"fake-image-bytes")

        media_id = client.upload_media(str(f))

        assert media_id == "fansly_media_01JR1234ABCD5678EFGH"


class TestUnsupportedEndpoints:
    def test_list_albums_raises_not_implemented(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        with pytest.raises(NotImplementedError):
            client.list_albums()

    def test_get_album_media_raises_not_implemented(self):
        client = FanslyApiClientImpl(api_key="sk_test")
        with pytest.raises(NotImplementedError):
            client.get_album_media("album_1")
