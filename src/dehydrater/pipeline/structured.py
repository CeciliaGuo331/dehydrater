"""让 LLM 输出 JSON，并用 pydantic 校验；不合格时把错误告诉模型，让它重写。"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from dehydrater.ports import ChatMessage, ChatModel, TokenUsage


class StructuredOutputError(Exception):
    pass


class InvalidReplyError(ValueError):
    """回复格式正确，但内容不满足业务约束（例如引用了不存在的编号）。"""


@dataclass(frozen=True)
class StructuredReply[T: BaseModel]:
    value: T
    usage: TokenUsage


async def complete_json[T: BaseModel](
    chat: ChatModel,
    messages: Sequence[ChatMessage],
    schema: type[T],
    *,
    check: Callable[[T], None] = lambda _: None,
    attempts: int = 3,
) -> StructuredReply[T]:
    """check 用于业务校验，发现问题时抛出 InvalidReplyError。"""
    conversation = list(messages)
    prompt_tokens = completion_tokens = 0
    error = ""
    for _ in range(attempts):
        reply = await chat.complete(conversation, json=True)
        prompt_tokens += reply.usage.prompt_tokens
        completion_tokens += reply.usage.completion_tokens
        try:
            value = schema.model_validate_json(_extract_json(reply.content))
            check(value)
        except (ValidationError, InvalidReplyError) as invalid:
            error = str(invalid)
            conversation += [
                ChatMessage("assistant", reply.content),
                ChatMessage("user", f"上面的输出不符合要求：\n{error}\n请修正后只输出 JSON。"),
            ]
            continue
        return StructuredReply(value, TokenUsage(prompt_tokens, completion_tokens))
    raise StructuredOutputError(f"模型连续 {attempts} 次输出不合格，最后一次的问题：{error}")


def _extract_json(content: str) -> str:
    """去掉模型可能包裹的 ```json 代码块等多余文字，取最外层的 JSON 对象。"""
    start, end = content.find("{"), content.rfind("}")
    return content[start : end + 1] if start != -1 and end > start else content
