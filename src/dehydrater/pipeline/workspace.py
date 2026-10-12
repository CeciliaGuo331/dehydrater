"""一节课的工作区：目录布局、lecture.toml 的读写、产物存储。"""

import hashlib
import tomllib
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import tomli_w
from pydantic import BaseModel, ConfigDict

from dehydrater.domain.base import DomainModel
from dehydrater.domain.lecture import Lecture, SourceFile
from dehydrater.pipeline.artifacts import ArtifactKey

LECTURE_FILE = "lecture.toml"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class WorkspaceError(Exception):
    pass


class _LectureManifest(BaseModel):
    """lecture.toml 的文件格式。路径可以是绝对路径，也可以相对于工作区。"""

    model_config = ConfigDict(extra="forbid")

    title: str
    date: date
    recording: Path
    slides: list[Path] = []


class Workspace:
    """工作区目录布局：

    lecture.toml            输入清单（用户可编辑）
    notes.md                笔记
    dehydrated.md           脱水逐字稿
    raw.md                  原始逐字稿
    cache/
        audio.mp3           从录音中提取的音频（送去语音识别的就是它）
        dehydrater.log      运行日志
        artifacts/          各阶段产物（JSON），如原始逐字稿、大纲
        stages/             各阶段的缓存元数据：缓存键、耗时、token 用量
        <阶段名>/           各阶段自己的中间文件，如脱水的分块结果
    删除 cache/ 等于从头开始。
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @classmethod
    def prepare(
        cls,
        root: Path,
        *,
        title: str,
        lecture_date: date,
        recording: Path,
        slides: Sequence[Path] = (),
    ) -> "Workspace":
        """新建工作区；已存在且处理的是同一个录音时沿用它（已完成的步骤不会重做）。"""
        workspace = cls(root)
        if workspace.manifest_path.exists():
            existing = workspace.resolve(workspace._read_manifest().recording).resolve()
            if existing != recording.resolve():
                raise WorkspaceError(
                    f"{workspace.root} 已用于整理另一节课（{existing.name}），请换一个输出路径"
                )
        manifest = _LectureManifest(
            title=title,
            date=lecture_date,
            recording=workspace.portable_path(recording),
            slides=[workspace.portable_path(path) for path in slides],
        )
        workspace.root.mkdir(parents=True, exist_ok=True)
        data = manifest.model_dump(mode="json")
        workspace.manifest_path.write_text(tomli_w.dumps(data), encoding="utf-8")
        return workspace

    @property
    def manifest_path(self) -> Path:
        return self.root / LECTURE_FILE

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def audio_path(self) -> Path:
        return self.cache_dir / "audio.mp3"

    @property
    def log_path(self) -> Path:
        return self.cache_dir / "dehydrater.log"

    def files_dir(self, stage: str) -> Path:
        """某个阶段自己的中间文件目录。"""
        return self.cache_dir / stage

    def stage_meta_path(self, stage: str) -> Path:
        return self.cache_dir / "stages" / f"{stage}.json"

    def resolve(self, path: Path) -> Path:
        """把产物中记录的路径（可能相对于工作区）转成绝对路径。"""
        return path if path.is_absolute() else self.root / path

    def portable_path(self, path: Path) -> Path:
        """工作区内的文件记为相对路径，便于整体移动工作区；工作区外的记为绝对路径。"""
        absolute = path.resolve()
        return absolute.relative_to(self.root) if absolute.is_relative_to(self.root) else absolute

    def load_lecture(self) -> Lecture:
        if not self.manifest_path.exists():
            raise WorkspaceError(f"{self.root} 不是工作区：找不到 {LECTURE_FILE}")
        manifest = self._read_manifest()
        return Lecture(
            title=manifest.title,
            date=manifest.date,
            recording=self._source_file(manifest.recording),
            slides=[self._source_file(path) for path in manifest.slides],
        )

    def _read_manifest(self) -> _LectureManifest:
        with self.manifest_path.open("rb") as f:
            return _LectureManifest.model_validate(tomllib.load(f))

    def _source_file(self, path: Path) -> SourceFile:
        absolute = self.resolve(path)
        if not absolute.is_file():
            raise WorkspaceError(f"找不到输入文件：{absolute}")
        stat = absolute.stat()
        return SourceFile(path=path, size=stat.st_size, mtime_ns=stat.st_mtime_ns)


class ArtifactStore:
    """以 JSON 文件保存产物，并提供内容摘要供缓存使用。"""

    def __init__(self, workspace: Workspace) -> None:
        self._dir = workspace.cache_dir / "artifacts"

    def exists(self, key: ArtifactKey[DomainModel]) -> bool:
        return self._path(key).exists()

    def read[M: DomainModel](self, key: ArtifactKey[M]) -> M:
        return key.model.model_validate_json(self._path(key).read_bytes())

    def write[M: DomainModel](self, key: ArtifactKey[M], value: M) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path(key).write_text(value.model_dump_json(indent=2), encoding="utf-8")

    def digest(self, key: ArtifactKey[DomainModel]) -> str | None:
        path = self._path(key)
        return sha256_of(path) if path.exists() else None

    def _path(self, key: ArtifactKey[DomainModel]) -> Path:
        return self._dir / f"{key.name}.json"
