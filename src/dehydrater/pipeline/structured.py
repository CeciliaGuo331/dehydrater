"""让 LLM 按约定格式输出，校验不合格时把错误告诉模型，让它重写。"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from dehydrater.ports import ChatMessage, ChatModel, TokenUsage

logger = logging.getLogger(__name__)


class StructuredOutputError(Exception):
    pass


class InvalidReplyError(ValueError):
    """回复不满足约定（格式错误，或引用了不存在的编号等）。"""


@dataclass(frozen=True)
class CheckedReply[T]:
    value: T
    usage: TokenUsage


async def complete_checked[T](
    chat: ChatModel,
    messages: Sequence[ChatMessage],
    parse: Callable[[str], T],
    *,
    json: bool = False,
    attempts: int = 3,
) -> CheckedReply[T]:
    """parse 把回复文本转成结果，发现问题时抛出 InvalidReplyError。"""
    conversation = list(messages)
    prompt_tokens = completion_tokens = 0
    error = ""
    for attempt in range(1, attempts + 1):
        reply = await chat.complete(conversation, json=json)
        prompt_tokens += reply.usage.prompt_tokens
        completion_tokens += reply.usage.completion_tokens
        try:
            value = parse(reply.content)
        except InvalidReplyError as invalid:
            error = str(invalid)
            logger.warning("模型输出不合格（第 %d/%d 次）：%s", attempt, attempts, error)
            logger.debug("不合格的输出原文：%s", reply.content)
            conversation += [
                ChatMessage("assistant", reply.content),
                ChatMessage("user", f"上面的输出不符合要求：\n{error}\n请修正后重新完整输出。"),
            ]
            continue
        return CheckedReply(value, TokenUsage(prompt_tokens, completion_tokens))
    raise StructuredOutputError(f"模型连续 {attempts} 次输出不合格，最后一次的问题：{error}")


async def complete_json[T: BaseModel](
    chat: ChatModel,
    messages: Sequence[ChatMessage],
    schema: type[T],
    *,
    check: Callable[[T], None] = lambda _: None,
) -> CheckedReply[T]:
    """要求输出一个符合 schema 的 JSON 对象；check 做业务校验，发现问题时抛出 InvalidReplyError。"""

    def parse(content: str) -> T:
        try:
            value = schema.model_validate_json(_extract_json(content))
        except ValidationError as invalid:
            raise InvalidReplyError(str(invalid)) from invalid
        check(value)
        return value

    return await complete_checked(chat, messages, parse, json=True)


def _extract_json(content: str) -> str:
    """去掉模型可能包裹的 ```json 代码块等多余文字，取最外层的 JSON 对象。"""
    start, end = content.find("{"), content.rfind("}")
    return content[start : end + 1] if start != -1 and end > start else content
