"""块级缓存：一个阶段内部的多次 LLM 调用各自落盘，中断后重跑只补齐缺失的部分。"""

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from pydantic import BaseModel


class JsonMemo:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    async def get_or_compute[T: BaseModel](
        self,
        material: Mapping[str, object],
        model: type[T],
        compute: Callable[[], Awaitable[T]],
    ) -> T:
        """material 是决定结果的全部输入；相同的 material 只计算一次。"""
        encoded = json.dumps(material, sort_keys=True, ensure_ascii=False).encode()
        path = self._directory / f"{hashlib.sha256(encoded).hexdigest()}.json"
        if path.exists():
            return model.model_validate_json(path.read_bytes())
        value = await compute()
        self._directory.mkdir(parents=True, exist_ok=True)
        path.write_text(value.model_dump_json(indent=2), encoding="utf-8")
        return value
