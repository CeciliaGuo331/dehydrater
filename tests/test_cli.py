"""命令行冒烟测试：参数解析、帮助信息、交互流程。不访问网络，不运行流水线。"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from dehydrater.cli import lecture, setup
from dehydrater.cli.app import app
from dehydrater.cli.shell_profile import ShellProfile
from dehydrater.config import Settings, Task
from dehydrater.service import LecturePlan

from .fakes import ScriptedAsk

runner = CliRunner()

_COMPLETE = {f"DEHYDRATER_{task.upper()}_KEY": "k" for task in Task}


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """隔离真实的环境变量和 .env；返回的字典即当前设置，可在测试中修改。"""
    values: dict[str, str] = {}
    for module in (lecture, setup):
        monkeypatch.setattr(module, "load_settings", lambda: Settings(values, []))
    return values


def test_help_is_short_usage() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "dehydrater setup" in result.output
    assert "notes.md" in result.output


def test_interactive_requires_setup(settings: dict[str, str]) -> None:
    result = runner.invoke(app, [])

    assert result.exit_code == 1
    assert "dehydrater setup" in result.output


def test_interactive_asks_until_answers_are_valid(
    settings: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.update(_COMPLETE)
    recording = _tone(tmp_path / "第3讲 2026-09-30.m4a")
    slides = tmp_path / "调度.pdf"
    slides.write_bytes(b"%PDF")
    planned: list[LecturePlan] = []

    def execute(plan: LecturePlan, _settings: Settings) -> None:
        planned.append(plan)

    monkeypatch.setattr(lecture, "execute", execute)
    ask = ScriptedAsk(
        "",  # 课堂名称：不能为空，重问
        "操作系统 第3讲",
        str(slides),  # 课堂资料：缺少录音，重问
        f"'{recording}' {slides}",
        str(tmp_path / "输出 目录"),  # 含空格也不需要引号
        "",  # 确认：回车即开始
    )

    lecture.interactive(ask)

    assert ask.labels == [
        "课堂名称",
        "课堂名称",
        "课堂资料",
        "课堂资料",
        "输出路径",
        "确认开始？(Y/n)",
    ]
    plan = planned[0]
    assert (plan.title, plan.recording, plan.slides) == ("操作系统 第3讲", recording, [slides])
    assert str(plan.lecture_date) == "2026-09-30"
    assert plan.output == tmp_path / "输出 目录"


def test_setup_reuses_previous_key_and_writes_shell_profile(
    settings: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def accept(_settings: Settings, _task: Task) -> None:
        pass

    monkeypatch.setattr(setup, "verify_task", accept)
    rc = tmp_path / ".zshrc"
    answers = ["", "", "asr-key"]  # 录音文件识别：地址和资源 ID 用默认值
    answers += ["", "", "ark-key"]  # 逐字稿脱水
    answers += ["", "ep-outline", ""] * 2  # 大纲与撰写：Key 回车沿用方舟的
    answers += ["1"]  # 写入 shell 启动文件

    setup.run_setup(ScriptedAsk(*answers), ShellProfile("zsh", rc))

    text = rc.read_text()
    assert "export DEHYDRATER_TRANSCRIBE_KEY=asr-key" in text
    assert "export DEHYDRATER_WRITE_NOTES_KEY=ark-key" in text
    assert "export DEHYDRATER_OUTLINE_MODEL=ep-outline" in text
    assert "export DEHYDRATER_DEHYDRATE_URL=https://ark.cn-beijing.volces.com/api/v3" in text


def test_process_reports_invalid_materials(settings: dict[str, str], tmp_path: Path) -> None:
    settings.update(_COMPLETE)
    slides = tmp_path / "调度.pdf"
    slides.write_bytes(b"%PDF")

    result = runner.invoke(
        app, ["process", "-n", "第3讲", "-i", str(slides), "-o", str(tmp_path / "out")]
    )

    assert result.exit_code == 1
    assert "恰好一个录音或录像" in result.output


def _tone(path: Path) -> Path:
    from .adapters.test_audio_pyav import _write_tone  # pyright: ignore[reportPrivateUsage]

    _write_tone(path, seconds=1.0)
    return path
