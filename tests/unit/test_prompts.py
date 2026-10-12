from pathlib import Path, PureWindowsPath

from dehydrater.cli.prompts import split_paths


def test_posix_paths_support_quotes_and_escaped_spaces() -> None:
    paths = split_paths("'/a b/录音.ts' /c\\ d/课件.pdf", windows=False)

    assert paths == [Path("/a b/录音.ts"), Path("/c d/课件.pdf")]


def test_windows_paths_keep_backslashes() -> None:
    parts = split_paths('"C:\\课程 资料\\录音.mp4" D:\\课件.pdf', windows=True)

    assert [PureWindowsPath(str(p)) for p in parts] == [
        PureWindowsPath("C:\\课程 资料\\录音.mp4"),
        PureWindowsPath("D:\\课件.pdf"),
    ]
