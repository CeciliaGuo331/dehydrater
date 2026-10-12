"""交互式输入。各流程依赖 Ask 协议而不是具体实现，测试时可以换成预设回答。"""

import os
import shlex
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from prompt_toolkit import prompt
from prompt_toolkit.completion import CompleteEvent, Completer, Completion, PathCompleter
from prompt_toolkit.document import Document


class Ask(Protocol):
    def __call__(
        self, label: str, *, default: str = "", secret: bool = False, paths: bool = False
    ) -> str:
        """显示 label 并读取一行输入；直接回车时返回 default。paths=True 时可按 Tab 补全路径。"""
        ...


def terminal_ask(
    label: str, *, default: str = "", secret: bool = False, paths: bool = False
) -> str:
    shown_default = "" if not default else " [已设置，回车沿用]" if secret else f" [{default}]"
    answer = prompt(
        f"{label}{shown_default}: ",
        is_password=secret,
        completer=_LastPathCompleter() if paths else None,
        complete_while_typing=False,
    ).strip()
    return answer or default


def split_paths(text: str, *, windows: bool = os.name == "nt") -> list[Path]:
    """按 shell 规则拆分：含空格的路径需要用引号括起来。

    POSIX 下反斜杠是转义符（拖入终端时空格会被转义成 "\\ "）；Windows 下反斜杠是路径分隔符，
    只能用引号，因此按非 POSIX 规则拆分后再去掉引号。
    """
    if windows:
        parts = [part.strip("\"'") for part in shlex.split(text, posix=False)]
    else:
        parts = shlex.split(text)
    return [Path(part).expanduser() for part in parts]


class _LastPathCompleter(Completer):
    """只补全最后一个路径，因为一行里可以输入多个路径。"""

    def __init__(self) -> None:
        self._paths = PathCompleter(expanduser=True)

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        last = document.text_before_cursor.rsplit(" ", 1)[-1].lstrip("'\"")
        yield from self._paths.get_completions(Document(last), complete_event)
