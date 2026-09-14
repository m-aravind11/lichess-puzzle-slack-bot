import asyncio
import hashlib
import hmac
import time

import pytest
from fastapi import HTTPException, Request

import slack_verify


def _run(coro):
    """No pytest-asyncio/anyio plugin in this project's deps - drive the
    coroutine directly instead of adding one just for these few tests."""
    return asyncio.run(coro)


def _request(body: bytes, headers: dict) -> Request:
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    return Request(scope, receive)


def _signed_headers(body: bytes, timestamp: str, secret: str) -> dict:
    basestring = f"v0:{timestamp}:{body.decode()}"
    signature = "v0=" + hmac.new(secret.encode(), basestring.encode(), hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature}


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setattr(slack_verify, "SLACK_SIGNING_SECRET", "test-secret")
    return "test-secret"


def test_valid_signature_is_accepted(secret):
    body = b"payload=hello"
    headers = _signed_headers(body, str(int(time.time())), secret)
    result = _run(slack_verify.verify_slack_request(_request(body, headers)))
    assert result == body


def test_missing_headers_are_rejected(secret):
    with pytest.raises(HTTPException) as exc_info:
        _run(slack_verify.verify_slack_request(_request(b"payload=hello", {})))
    assert exc_info.value.status_code == 401


def test_stale_timestamp_is_rejected(secret):
    body = b"payload=hello"
    old_timestamp = str(int(time.time()) - 600)
    headers = _signed_headers(body, old_timestamp, secret)
    with pytest.raises(HTTPException) as exc_info:
        _run(slack_verify.verify_slack_request(_request(body, headers)))
    assert exc_info.value.status_code == 401


def test_wrong_signature_is_rejected(secret):
    body = b"payload=hello"
    headers = _signed_headers(body, str(int(time.time())), "a-different-secret")
    with pytest.raises(HTTPException) as exc_info:
        _run(slack_verify.verify_slack_request(_request(body, headers)))
    assert exc_info.value.status_code == 401


def test_tampered_body_is_rejected(secret):
    body = b"payload=hello"
    headers = _signed_headers(body, str(int(time.time())), secret)
    tampered = _request(b"payload=goodbye", headers)
    with pytest.raises(HTTPException) as exc_info:
        _run(slack_verify.verify_slack_request(tampered))
    assert exc_info.value.status_code == 401
