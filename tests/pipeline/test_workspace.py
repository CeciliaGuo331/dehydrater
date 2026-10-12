from datetime import date
from pathlib import Path

import pytest

from dehydrater.pipeline.workspace import Workspace, WorkspaceError

_DATE = date(2026, 9, 30)


@pytest.fixture
def recording(tmp_path: Path) -> Path:
    path = tmp_path / "lecture.mp4"
    path.write_bytes(b"video")
    return path


def test_prepare_and_load_lecture(tmp_path: Path, recording: Path) -> None:
    slides = [tmp_path / "a.pdf", tmp_path / "b.pdf"]
    for path in slides:
        path.write_bytes(b"%PDF")

    Workspace.prepare(
        tmp_path / "L03", title="进程调度", lecture_date=_DATE, recording=recording, slides=slides
    )
    lecture = Workspace(tmp_path / "L03").load_lecture()

    assert lecture.title == "进程调度"
    assert lecture.date == _DATE
    assert lecture.recording.size == len(b"video")
    assert [s.path.name for s in lecture.slides] == ["a.pdf", "b.pdf"]


def test_prepare_reuses_workspace_of_same_recording(tmp_path: Path, recording: Path) -> None:
    root = tmp_path / "L03"
    Workspace.prepare(root, title="旧标题", lecture_date=_DATE, recording=recording)

    Workspace.prepare(root, title="新标题", lecture_date=_DATE, recording=recording)

    assert Workspace(root).load_lecture().title == "新标题"


def test_prepare_refuses_workspace_of_another_recording(tmp_path: Path, recording: Path) -> None:
    root = tmp_path / "L03"
    Workspace.prepare(root, title="t", lecture_date=_DATE, recording=recording)
    other = tmp_path / "other.mp4"
    other.write_bytes(b"")

    with pytest.raises(WorkspaceError, match="另一节课"):
        Workspace.prepare(root, title="t", lecture_date=_DATE, recording=other)


def test_files_inside_workspace_are_stored_relative(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "L03")
    inside = tmp_path / "L03" / "sources" / "a.mp4"
    outside = tmp_path / "elsewhere" / "b.mp4"

    assert workspace.portable_path(inside) == Path("sources/a.mp4")
    assert workspace.portable_path(outside) == outside.resolve()


def test_missing_source_file_is_reported(tmp_path: Path, recording: Path) -> None:
    workspace = Workspace.prepare(
        tmp_path / "L03", title="t", lecture_date=_DATE, recording=recording
    )
    recording.unlink()

    with pytest.raises(WorkspaceError, match="找不到输入文件"):
        workspace.load_lecture()
