import hashlib
import hmac
import logging
import os
import time

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

SLACK_SIGNING_SECRET = os.environ['SLACK_SIGNING_SECRET']


async def verify_slack_request(request: Request) -> bytes:
    body = await request.body()
    timestamp = request.headers.get('X-Slack-Request-Timestamp', '')
    slack_signature = request.headers.get('X-Slack-Signature', '')

    if not timestamp or not slack_signature:
        logger.warning("Rejected Slack request: missing signature headers")
        raise HTTPException(status_code=401, detail="Missing Slack signature headers")

    age = abs(time.time() - int(timestamp))
    if age > 60 * 5:
        logger.warning("Rejected Slack request: timestamp %.0fs old", age)
        raise HTTPException(status_code=401, detail="Stale request")

    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    computed_signature = 'v0=' + hmac.new(
        SLACK_SIGNING_SECRET.encode(), sig_basestring.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_signature, slack_signature):
        # Never log the signatures themselves - logging that they mismatched is
        # enough to debug a signing-secret misconfiguration without leaking them.
        logger.warning("Rejected Slack request: signature mismatch")
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    return body
