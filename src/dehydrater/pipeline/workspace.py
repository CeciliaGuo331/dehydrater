"""一节课的工作区：目录布局、lecture.toml 的读写、产物存储。"""

import hashlib
import tomllib
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
    video: Path
    slides: Path | None = None


class Workspace:
    """工作区目录布局：

    lecture.toml        输入清单（用户可编辑）
    .cache/artifacts/   各阶段产物（JSON）
    .cache/stages/      各阶段的缓存元数据
    .cache/files/       各阶段的二进制中间文件（如音频）
    assets/             讲义引用的图片
    *.md                最终输出
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @classmethod
    def create(
        cls, root: Path, *, title: str, lecture_date: date, video: Path, slides: Path | None
    ) -> "Workspace":
        if (root / LECTURE_FILE).exists():
            raise WorkspaceError(f"{root} 已经是一个工作区")
        workspace = cls(root)
        manifest = _LectureManifest(
            title=title,
            date=lecture_date,
            video=workspace.portable_path(video),
            slides=workspace.portable_path(slides) if slides else None,
        )
        workspace.root.mkdir(parents=True, exist_ok=True)
        data = manifest.model_dump(mode="json", exclude_none=True)
        workspace.manifest_path.write_text(tomli_w.dumps(data), encoding="utf-8")
        return workspace

    @property
    def manifest_path(self) -> Path:
        return self.root / LECTURE_FILE

    @property
    def cache_dir(self) -> Path:
        return self.root / ".cache"

    @property
    def assets_dir(self) -> Path:
        return self.root / "assets"

    def files_dir(self, stage: str) -> Path:
        """某个阶段专用的二进制文件目录。"""
        return self.cache_dir / "files" / stage

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
        with self.manifest_path.open("rb") as f:
            manifest = _LectureManifest.model_validate(tomllib.load(f))
        return Lecture(
            title=manifest.title,
            date=manifest.date,
            video=self._source_file(manifest.video),
            slides=self._source_file(manifest.slides) if manifest.slides else None,
        )

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
