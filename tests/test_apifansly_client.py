"""Contract tests for the automated PPV APIFansly adapter."""

from unittest.mock import MagicMock

import httpx
import pytest

from src.apifansly_client import ApifanslyClient, ApifanslyConfig
from src.fansly_client import AuthError, FanslyApiClient


def _response(payload: dict, status: int = 200) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status
    response.headers = {}
    response.json.return_value = payload
    response.raise_for_status = MagicMock()
    response.request = MagicMock(spec=httpx.Request)
    if status >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error",
            request=response.request,
            response=response,
        )
    return response


def _payload(response, *, cursor=None):
    return {
        "statusCode": 200,
        "data": {
            "status_code": 200,
            "data": {
                "success": True,
                "response": response,
            },
            "nextCursor": cursor,
        },
    }


def _client() -> ApifanslyClient:
    return ApifanslyClient(
        ApifanslyConfig(
            api_key="api_test",
            account_id="fansly_acc_test",
            webhook_token="w" * 32,
            max_retries=1,
        )
    )


def test_implements_provider_contract_and_required_capabilities():
    client = _client()

    assert isinstance(client, FanslyApiClient)
    assert client.capabilities.supports_paid_messages is True
    assert client.capabilities.supports_vault_albums is True
    assert client.capabilities.supports_attributed_purchases is True


def test_purchase_attribution_requires_webhook_route_token():
    client = ApifanslyClient(
        ApifanslyConfig(
            api_key="api_test",
            account_id="fansly_acc_test",
            webhook_token="too-short",
        )
    )

    assert client.capabilities.supports_attributed_purchases is False


def test_verify_auth_resolves_numeric_creator_id():
    client = _client()
    client.client.request = MagicMock(
        return_value=_response(
            _payload({"account": {"id": "creator-123"}})
        )
    )

    assert client.verify_auth() is True
    assert client.creator_fansly_id == "creator-123"


def test_missing_credentials_fail_without_network_request():
    client = ApifanslyClient(
        ApifanslyConfig(api_key="", account_id="")
    )
    client.client.request = MagicMock()

    with pytest.raises(AuthError, match="APIFANSLY_API_KEY"):
        client.verify_auth()

    client.client.request.assert_not_called()


def test_lists_cursor_paginated_chats_from_documented_shape():
    client = _client()
    client.client.request = MagicMock(
        return_value=_response(
            _payload(
                {
                    "data": [{
                        "groupId": "chat-1",
                        "partnerAccountId": "fan-1",
                        "partnerUsername": "buyer",
                        "unreadCount": 2,
                        "lastMessageId": "message-2",
                        "lastUnreadMessageId": "message-2",
                        "subscriptionTierId": None,
                    }],
                    "aggregationData": {
                        "accounts": [{
                            "id": "fan-1",
                            "username": "buyer",
                            "displayName": "Buyer",
                            "avatar": {
                                "locations": [{
                                    "location": "https://cdn.example/avatar.jpg"
                                }]
                            },
                        }]
                    },
                },
                cursor="cursor-2",
            )
        )
    )

    chats, cursor = client.list_chats_page(
        offset="cursor-1",
        order="unread",
    )

    assert cursor == "cursor-2"
    assert chats[0].partner_username == "buyer"
    assert chats[0].last_unread_message_id == "message-2"
    assert client.client.request.call_args.kwargs["params"] == {
        "filter": "all",
        "sort": "unread",
        "cursor": "cursor-1",
    }


def test_message_author_uses_numeric_creator_id():
    client = _client()
    client._creator_fansly_id = "creator-123"
    client.client.request = MagicMock(
        return_value=_response(
            _payload({
                "messages": [{
                    "id": "message-1",
                    "content": "hello",
                    "senderId": "fan-1",
                    "createdAt": 1774700000,
                    "attachments": [],
                }],
                "cursor": None,
            })
        )
    )

    messages, cursor = client.list_messages("chat-1", limit=100)

    assert cursor is None
    assert messages[0].is_from_fan is True
    assert client.client.request.call_args.kwargs["params"]["limit"] == 10


def test_sends_locked_ppv_with_preview_and_dollar_price():
    client = _client()
    client.client.request = MagicMock(
        return_value=_response(
            _payload({
                "id": "sent-1",
                "content": "unlock me",
                "createdAt": 1774754024,
                "attachments": [{
                    "contentType": 1,
                    "contentId": "account-media-1",
                }],
            }),
            status=201,
        )
    )

    sent = client.send_ppv(
        "chat-1",
        "unlock me",
        "media-1",
        25.0,
        preview_id="preview-1",
    )

    assert sent.message_id == "sent-1"
    assert sent.purchase_reference_id == "account-media-1"
    assert client.client.request.call_args.kwargs["json"] == {
        "content": "unlock me",
        "mediaIds": [{
            "mediaId": "media-1",
            "previewId": "preview-1",
        }],
        "access_type": ["ppv"],
        "price": 25.0,
    }


@pytest.mark.parametrize("price", [0.99, 500.01])
def test_rejects_out_of_range_ppv_price_without_request(price):
    client = _client()
    client.client.request = MagicMock()

    with pytest.raises(ValueError, match="between"):
        client.send_ppv("chat-1", "unlock", "media-1", price)

    client.client.request.assert_not_called()


def test_lists_vault_albums_and_media():
    client = _client()
    client.client.request = MagicMock(
        side_effect=[
            _response(_payload({"albums": [{"id": "album-1"}]})),
            _response(_payload({
                "media": [{
                    "id": "account-media-1",
                    "mediaId": "media-1",
                    "previewId": "preview-1",
                }],
                "cursor": "next-media",
            })),
        ]
    )

    assert client.list_albums() == [{"id": "album-1"}]
    media, cursor = client.get_album_media("album-1")
    assert media[0]["mediaId"] == "media-1"
    assert cursor == "next-media"
