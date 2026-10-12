from collections.abc import Sequence
from functools import cached_property

from openai import AsyncOpenAI, omit
from openai.types.chat import ChatCompletionMessageParam

from dehydrater.ports import ChatMessage, ChatReply, Fingerprint, TokenUsage


class OpenAICompatibleChatModel:
    """任何兼容 OpenAI Chat Completions 接口的服务：火山方舟、DeepSeek 等。"""

    def __init__(
        self, *, base_url: str, api_key: str, model: str, temperature: float | None
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._temperature = temperature

    @cached_property
    def _client(self) -> AsyncOpenAI:
        # 首次调用时才创建：SDK 在密钥为空时会直接报错，而 status 等命令不需要密钥
        return AsyncOpenAI(base_url=self._base_url, api_key=self._api_key)

    def fingerprint(self) -> Fingerprint:
        return {"base_url": self._base_url, "model": self._model, "temperature": self._temperature}

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatReply:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[_to_param(message) for message in messages],
            # 未配置时不发送该字段（发送 null 会被部分服务拒绝）
            temperature=omit if self._temperature is None else self._temperature,
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
