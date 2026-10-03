"""The model behind "ask in plain English" (masterplan 5.28): Claude's Messages API with tool use. It is given read-only lookups and
nothing else; it never sees raw records and cannot run anything that changes data. Without a key (and not in test mode) asking is off."""

import logging
from typing import Protocol

import httpx

from app.config import settings

log = logging.getLogger(__name__)
URL = "https://api.anthropic.com/v1/messages"


class AskError(Exception):
    """The question could not be answered. The text is safe to show."""


class LLM(Protocol):
    name: str

    async def complete(self, system: str, messages: list[dict], tools: list[dict]) -> dict: ...


class FakeLLM:
    """Tests and local development: replies come from `handler(messages)`, which returns {"text": ..., "tool_calls": [{id, name, input}]}."""

    name = "fake"

    def __init__(self) -> None:
        self.handler = None
        self.fail_with: str | None = None
        self.calls: list[dict] = []

    async def complete(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        if self.fail_with:
            raise AskError(self.fail_with)
        if self.handler is None:
            return {"text": "I cannot answer that.", "tool_calls": []}
        return self.handler(messages)


class ClaudeLLM:
    name = "claude"

    async def complete(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        body = {"model": settings.ask_model, "max_tokens": 1024, "system": system, "tools": tools, "messages": messages}
        headers = {"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=60) as http:
                res = await http.post(URL, headers=headers, json=body)
                res.raise_for_status()
                blocks = res.json()["content"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("The question-answering service did not answer: %s", type(e).__name__)
            raise AskError("The question could not be answered just now. Try again in a moment.") from None
        return {
            "text": "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip(),
            "tool_calls": [{"id": b["id"], "name": b["name"], "input": b.get("input") or {}} for b in blocks if b.get("type") == "tool_use"],
            "raw_blocks": blocks,
        }


_fake = FakeLLM()


def get_llm() -> LLM:
    if settings.ask_llm == "fake":
        return _fake
    if settings.anthropic_api_key and settings.ask_llm in ("", "claude"):
        return ClaudeLLM()
    raise AskError("Asking questions in plain English is not switched on for this system. The example questions below still work.")


def fake_llm() -> FakeLLM:
    return _fake
