"""多处测试共用的替身。"""

from collections.abc import Sequence

from dehydrater.credentials import KeychainUnavailableError
from dehydrater.ports import ChatMessage, ChatReply, Fingerprint, TokenUsage


class FakeKeychain:
    def __init__(self, entries: dict[str, str] | None = None, *, available: bool = True) -> None:
        self.entries = dict(entries or {})
        self._available = available

    def get(self, name: str) -> str | None:
        return self.entries.get(name)

    def set(self, name: str, value: str) -> None:
        if not self._available:
            raise KeychainUnavailableError("没有可用的钥匙串")
        self.entries[name] = value

    def delete(self, name: str) -> bool:
        return self.entries.pop(name, None) is not None


class ScriptedChat:
    """按顺序返回预设回复的 ChatModel，并记录收到的消息。"""

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.calls: list[list[ChatMessage]] = []
        self.json_modes: list[bool] = []

    def fingerprint(self) -> Fingerprint:
        return {"model": "scripted"}

    async def complete(self, messages: Sequence[ChatMessage], *, json: bool = False) -> ChatReply:
        self.calls.append(list(messages))
        self.json_modes.append(json)
        return ChatReply(self._replies.pop(0), TokenUsage(prompt_tokens=10, completion_tokens=5))
