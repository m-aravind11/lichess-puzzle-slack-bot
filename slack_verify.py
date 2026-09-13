import hashlib
import hmac
import os
import time

from fastapi import HTTPException, Request

SLACK_SIGNING_SECRET = os.environ['SLACK_SIGNING_SECRET']


async def verify_slack_request(request: Request) -> bytes:
    body = await request.body()
    timestamp = request.headers.get('X-Slack-Request-Timestamp', '')
    slack_signature = request.headers.get('X-Slack-Signature', '')

    if not timestamp or not slack_signature:
        raise HTTPException(status_code=401, detail="Missing Slack signature headers")

    if abs(time.time() - int(timestamp)) > 60 * 5:
        raise HTTPException(status_code=401, detail="Stale request")

    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    computed_signature = 'v0=' + hmac.new(
        SLACK_SIGNING_SECRET.encode(), sig_basestring.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_signature, slack_signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    return body
