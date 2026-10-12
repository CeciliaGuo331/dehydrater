"""在伪终端中运行真正的 dehydrater 命令，覆盖 prompt_toolkit 输入、Typer 解析、rich 输出的完整路径。

只走到确认这一步并回答"否"，不调用任何在线服务。
"""

import contextlib
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

pexpect = pytest.importorskip("pexpect")
pyte = pytest.importorskip("pyte")
pytestmark = [
    pytest.mark.skipif(sys.platform == "win32", reason="pexpect 需要类 Unix 伪终端"),
    # pytest 进程中已有其他线程，forkpty 会警告；子进程立即 exec，不受影响
    pytest.mark.filterwarnings("ignore:This process .* is multi-threaded"),
]

_EXECUTABLE = shutil.which("dehydrater")


class _Screen:
    """用 pyte 渲染终端输出，检查用户在屏幕上实际看到的内容（而不只是输出过的字节）。"""

    def __init__(self, child) -> None:
        self._child = child
        self._screen = pyte.Screen(160, 40)
        self._stream = pyte.Stream(self._screen)

    def settle(self, seconds: float = 1.5) -> str:
        """等待界面稳定（动画会持续刷新），返回当前屏幕上光标所在行。"""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            with contextlib.suppress(pexpect.TIMEOUT):
                self._stream.feed(self._child.read_nonblocking(65536, timeout=0.1))
        return self._screen.display[self._screen.cursor.y]


def _spawn(tmp_path: Path, env: dict[str, str], *args: str, term: str = "dumb"):
    assert _EXECUTABLE, "未找到 dehydrater 命令，请先 uv sync"
    return pexpect.spawn(
        _EXECUTABLE,
        list(args),
        cwd=str(tmp_path),  # 避免读到项目根目录的 .env
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TERM": term, **env},
        encoding="utf-8",
        dimensions=(40, 160),
        timeout=30,
    )


def test_requires_setup_before_organizing(tmp_path: Path) -> None:
    child = _spawn(tmp_path, {})

    child.expect("dehydrater setup")
    child.expect(pexpect.EOF)
    child.close()

    assert child.exitstatus == 1


def test_interactive_flow_until_confirmation(tmp_path: Path) -> None:
    from ..adapters.test_audio_pyav import _write_tone  # pyright: ignore[reportPrivateUsage]

    materials = tmp_path / "素材 目录"
    materials.mkdir()
    recording = materials / "第3讲 2026-09-30.m4a"
    _write_tone(recording, seconds=1.0)
    keys = {
        f"DEHYDRATER_{task}_KEY": "k"
        for task in ("TRANSCRIBE", "DEHYDRATE", "OUTLINE", "WRITE_NOTES")
    }
    child = _spawn(tmp_path, keys)

    child.expect("课堂名称")
    child.sendline("")  # 不能为空
    child.expect("不能为空")
    child.sendline("操作系统 第3讲")
    child.expect("课堂资料")
    child.sendline(f"'{recording}'")
    child.expect("输出路径")
    child.sendline(str(tmp_path / "输出 目录"))  # 含空格，不加引号
    child.expect("取自文件名")
    child.expect("确认开始")
    child.sendline("n")
    child.expect(pexpect.EOF)
    child.close()

    assert child.exitstatus == 0
    assert not (tmp_path / "输出 目录").exists()


def test_setup_retry_question_stays_visible(tmp_path: Path) -> None:
    """验证失败后的"重新输入"提问必须停留在屏幕上。

    曾经的问题：提问在"验证中"动画结束前弹出，动画不断重绘同一行把提问盖住，看起来像卡死。
    用真实终端类型运行（动画开启），并渲染屏幕检查用户实际看到的内容。
    """
    unreachable = "http://127.0.0.1:9/api"  # discard 端口，连接会被立即拒绝
    child = _spawn(tmp_path, {"SHELL": "/bin/sh"}, "setup", term="xterm-256color")
    screen = _Screen(child)

    for answer in (unreachable, "", "key"):
        child.expect(r"(接入地址|资源 ID|API Key)")
        child.sendline(answer)
    assert "重新输入这一项" in screen.settle()

    child.sendline("n")
    for _ in range(3):  # 其余三个任务同样回答，确认流程能走完
        for answer in (unreachable, "", "key"):
            child.expect(r"(接入地址|模型/接入点 ID|API Key)")
            child.sendline(answer)
        child.expect("重新输入这一项")
        child.sendline("n")
    child.expect("请选择保存方式")
    child.sendline("2")  # 只显示配置片段
    child.expect("DEHYDRATER_WRITE_NOTES_KEY")
    child.expect(pexpect.EOF)
    child.close()

    assert child.exitstatus == 0
