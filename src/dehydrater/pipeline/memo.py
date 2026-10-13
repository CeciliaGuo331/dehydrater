"""块级缓存：一个阶段内部的多次 LLM 调用各自落盘，中断后重跑只补齐缺失的部分。

缓存的同时保存当初调用花费的 token，沿用缓存时照样计入，
这样各阶段统计的始终是"产出这份结果的完整成本"，而不只是本次新花的部分。
"""

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from pydantic import BaseModel

from dehydrater.ports import TokenUsage

logger = logging.getLogger(__name__)

# 缓存文件格式变化时加一，旧格式的文件自然不再命中
_FORMAT = 2


class JsonMemo:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    async def get_or_compute[T: BaseModel](
        self,
        material: Mapping[str, object],
        model: type[T],
        compute: Callable[[], Awaitable[tuple[T, TokenUsage]]],
    ) -> tuple[T, TokenUsage]:
        """material 是决定结果的全部输入；相同的 material 只计算一次。"""
        encoded = json.dumps(
            {"format": _FORMAT, **material}, sort_keys=True, ensure_ascii=False
        ).encode()
        path = self._directory / f"{hashlib.sha256(encoded).hexdigest()}.json"
        if path.exists():
            logger.debug("沿用已缓存的结果 %s", path.name)
            stored = json.loads(path.read_bytes())
            return model.model_validate(stored["value"]), TokenUsage(**stored["usage"])
        value, usage = await compute()
        logger.debug("已缓存结果 %s", path.name)
        self._directory.mkdir(parents=True, exist_ok=True)
        stored = {
            "value": value.model_dump(mode="json"),
            "usage": {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
            },
        }
        path.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
        return value, usage
