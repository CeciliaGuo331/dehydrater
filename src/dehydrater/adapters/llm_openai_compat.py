import asyncio
import json as jsonlib
from collections.abc import Mapping, Sequence
from functools import cached_property

from openai import AsyncOpenAI, omit
from openai.types.chat import ChatCompletionMessageParam

from dehydrater.ports import ChatMessage, ChatReply, Fingerprint, TokenUsage


class OpenAICompatibleChatModel:
    """任何兼容 OpenAI Chat Completions 接口的服务：火山方舟、DeepSeek 等。

    限流与重试：并发数由 max_concurrency 限制；429、5xx 和超时由 openai SDK 自动重试。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float | None,
        max_tokens: int | None,
        extra_body: Mapping[str, object],
        max_concurrency: int,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._extra_body = dict(extra_body)
        self._slots = asyncio.Semaphore(max_concurrency)

    @cached_property
    def _client(self) -> AsyncOpenAI:
        # 首次调用时才创建：SDK 在密钥为空时会直接报错，而 status 等命令不需要密钥
        return AsyncOpenAI(base_url=self._base_url, api_key=self._api_key, max_retries=4)

    def fingerprint(self) -> Fingerprint:
        return {
            "base_url": self._base_url,
            "model": self._model,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "extra_body": jsonlib.dumps(self._extra_body, sort_keys=True),
        }

    async def complete(self, messages: Sequence[ChatMessage], *, json: bool = False) -> ChatReply:
        async with self._slots:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[_to_param(message) for message in messages],
                # 未配置时不发送这些字段（发送 null 会被部分服务拒绝）
                temperature=omit if self._temperature is None else self._temperature,
                max_tokens=omit if self._max_tokens is None else self._max_tokens,
                response_format={"type": "json_object"} if json else omit,
                extra_body=self._extra_body or None,
            )
        usage = response.usage
        return ChatReply(
            content=response.choices[0].message.content or "",
            usage=TokenUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
            ),
        )


def _to_param(message: ChatMessage) -> ChatCompletionMessageParam:
    match message.role:
        case "system":
            return {"role": "system", "content": message.content}
        case "user":
            return {"role": "user", "content": message.content}
        case "assistant":
            return {"role": "assistant", "content": message.content}
