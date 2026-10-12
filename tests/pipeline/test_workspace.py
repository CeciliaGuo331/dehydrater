from datetime import date
from pathlib import Path

import pytest

from dehydrater.pipeline.workspace import Workspace, WorkspaceError


def test_create_and_load_lecture(tmp_path: Path) -> None:
    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"video")
    root = tmp_path / "L03"

    Workspace.create(root, title="进程调度", lecture_date=date(2026, 10, 12), recording=video)
    lecture = Workspace(root).load_lecture()

    assert lecture.title == "进程调度"
    assert lecture.date == date(2026, 10, 12)
    assert lecture.recording.size == len(b"video")
    assert lecture.slides is None


def test_files_inside_workspace_are_stored_relative(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "L03")
    inside = tmp_path / "L03" / "sources" / "a.mp4"
    outside = tmp_path / "elsewhere" / "b.mp4"

    assert workspace.portable_path(inside) == Path("sources/a.mp4")
    assert workspace.portable_path(outside) == outside.resolve()


def test_missing_source_file_is_reported(tmp_path: Path) -> None:
    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"video")
    workspace = Workspace.create(
        tmp_path / "L03", title="t", lecture_date=date(2026, 1, 1), recording=video
    )
    video.unlink()

    with pytest.raises(WorkspaceError, match="找不到输入文件"):
        workspace.load_lecture()


def test_create_refuses_existing_workspace(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"")
    Workspace.create(tmp_path, title="t", lecture_date=date(2026, 1, 1), recording=video)

    with pytest.raises(WorkspaceError, match="已经是一个工作区"):
        Workspace.create(tmp_path, title="t", lecture_date=date(2026, 1, 1), recording=video)
