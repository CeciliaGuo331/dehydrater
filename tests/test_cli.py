"""CLI 冒烟测试：只验证参数解析和不依赖外部服务的命令。"""

from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from dehydrater.cli import app

runner = CliRunner()


def test_config_init_then_check_reports_missing_secrets(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"

    assert runner.invoke(app, ["config", "init", "--config", str(config)]).exit_code == 0
    result = runner.invoke(app, ["config", "check", "--config", str(config)], env={})

    assert result.exit_code == 1
    assert "ARK_API_KEY" in result.output


def test_init_then_status(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    runner.invoke(app, ["config", "init", "--config", str(config)])
    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"")
    workspace = tmp_path / "L01"

    init = runner.invoke(
        app, ["init", str(workspace), "--video", str(video), "--date", str(date(2026, 10, 12))]
    )
    status = runner.invoke(app, ["status", str(workspace), "--config", str(config)])

    assert init.exit_code == 0, init.output
    assert status.exit_code == 0, status.output
    assert "extract_audio" in status.output
