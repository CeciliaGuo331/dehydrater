"""多处测试共用的替身。"""

from collections.abc import Sequence

from dehydrater.ports import ChatMessage, ChatReply, Fingerprint, TokenUsage


class ScriptedChat:
    """按顺序返回预设回复的 ChatModel，并记录收到的消息。"""

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.calls: list[list[ChatMessage]] = []
        self.json_modes: list[bool] = []

    def fingerprint(self) -> Fingerprint:
        return {"model": "scripted"}

    async def verify(self) -> None:
        pass

    async def complete(self, messages: Sequence[ChatMessage], *, json: bool = False) -> ChatReply:
        self.calls.append(list(messages))
        self.json_modes.append(json)
        return ChatReply(self._replies.pop(0), TokenUsage(prompt_tokens=10, completion_tokens=5))


class ScriptedAsk:
    """按顺序给出预设回答的 Ask；回答为空字符串时等同直接回车，采用默认值。"""

    def __init__(self, *answers: str) -> None:
        self._answers = list(answers)
        self.labels: list[str] = []

    def __call__(
        self, label: str, *, default: str = "", secret: bool = False, paths: bool = False
    ) -> str:
        self.labels.append(label.strip())
        return self._answers.pop(0) or default
