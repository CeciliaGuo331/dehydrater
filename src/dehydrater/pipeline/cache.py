"""阶段级缓存：根据输入和参数计算缓存键，判断能否跳过某个阶段。"""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from dehydrater.pipeline.stage import Stage
from dehydrater.pipeline.workspace import ArtifactStore
from dehydrater.ports import TokenUsage


class StageMeta(BaseModel):
    """一个阶段最近一次成功运行的记录，保存在 cache/stages/<stage>.json。"""

    cache_key: str
    output_digests: dict[str, str]
    elapsed_seconds: float
    prompt_tokens: int
    completion_tokens: int


def compute_cache_key(stage: Stage, store: ArtifactStore) -> str | None:
    """输入产物不全时返回 None，表示该阶段现在还无法运行。"""
    input_digests: dict[str, str] = {}
    for key in stage.inputs:
        digest = store.digest(key)
        if digest is None:
            return None
        input_digests[key.name] = digest
    material = {
        "stage": stage.name,
        "version": stage.version,
        "fingerprint": dict(stage.fingerprint()),
        "inputs": input_digests,
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_meta(path: Path) -> StageMeta | None:
    return StageMeta.model_validate_json(path.read_bytes()) if path.exists() else None


def save_meta(
    path: Path,
    *,
    cache_key: str,
    stage: Stage,
    store: ArtifactStore,
    elapsed_seconds: float,
    usage: TokenUsage,
) -> None:
    output_digests = {key.name: store.digest(key) or "" for key in stage.outputs}
    meta = StageMeta(
        cache_key=cache_key,
        output_digests=output_digests,
        elapsed_seconds=elapsed_seconds,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")


def is_fresh(meta: StageMeta | None, cache_key: str, stage: Stage, store: ArtifactStore) -> bool:
    """缓存键一致，且输出产物没有被删除或改动过。"""
    if meta is None or meta.cache_key != cache_key:
        return False
    return all(store.digest(key) == meta.output_digests.get(key.name) for key in stage.outputs)
