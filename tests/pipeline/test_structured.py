import pytest
from pydantic import BaseModel

from dehydrater.pipeline.structured import (
    InvalidReplyError,
    StructuredOutputError,
    complete_json,
)
from dehydrater.ports import ChatMessage

from ..fakes import ScriptedChat


class Answer(BaseModel):
    value: int


def _positive(answer: Answer) -> None:
    if answer.value <= 0:
        raise InvalidReplyError("value 必须为正数")


async def test_extracts_json_wrapped_in_code_fence() -> None:
    chat = ScriptedChat('好的：\n```json\n{"value": 3}\n```')

    reply = await complete_json(chat, [ChatMessage("user", "q")], Answer)

    assert reply.value == Answer(value=3)


async def test_retries_with_error_feedback_then_succeeds() -> None:
    chat = ScriptedChat('{"value": -1}', '{"value": 2}')

    reply = await complete_json(chat, [ChatMessage("user", "q")], Answer, check=_positive)

    assert reply.value == Answer(value=2)
    assert "value 必须为正数" in chat.calls[1][-1].content
    assert reply.usage.prompt_tokens == 20


async def test_gives_up_after_attempts() -> None:
    chat = ScriptedChat("不是 JSON", "还不是", "仍然不是")

    with pytest.raises(StructuredOutputError):
        await complete_json(chat, [ChatMessage("user", "q")], Answer)
