"""Push notifications to a phone through Expo's push service. A push is a nudge on top of the text message, never the only way a person is
told, so nothing here ever raises into the caller: a push service that is down or an address that has gone stale must not stop an SOS."""

import logging

import httpx

log = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
SOS_CHANNEL = "sos"  # the Android notification channel the app creates, loud and shown over everything


async def _post(messages: list[dict]) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.post(EXPO_PUSH_URL, json=messages, headers={"Accept": "application/json"})
        res.raise_for_status()


async def send(tokens: list[str], title: str, body: str, data: dict | None = None, *, channel: str | None = None) -> None:
    """Sends one notification to each phone address. Addresses that are not Expo push tokens are skipped."""
    messages = [
        {"to": t, "title": title, "body": body, "data": data or {}, "sound": "default", "priority": "high", **({"channelId": channel} if channel else {})}
        for t in dict.fromkeys(tokens)  # each phone once
        if t.startswith(("ExponentPushToken[", "ExpoPushToken["))
    ]
    if not messages:
        return
    try:
        await _post(messages)
    except Exception:  # noqa: BLE001 - see the module note
        log.warning("A push notification could not be sent to %d phone(s)", len(messages))
