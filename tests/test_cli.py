"""CLI 冒烟测试：只验证参数解析和不依赖外部服务的命令。"""

from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dehydrater import cli
from dehydrater.credentials import SecretStore

from .fakes import FakeKeychain

runner = CliRunner()


@pytest.fixture
def keychain(monkeypatch: pytest.MonkeyPatch) -> FakeKeychain:
    """隔离真实的环境变量、.env 和系统钥匙串。"""
    fake = FakeKeychain()
    monkeypatch.setattr(cli, "build_secret_store", lambda: SecretStore({}, [], fake))
    return fake


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    assert runner.invoke(cli.app, ["config", "init", "--config", str(path)]).exit_code == 0
    return path


def test_config_check_lists_providers_without_keys(config: Path, keychain: FakeKeychain) -> None:
    keychain.entries["transcribe"] = "k"

    result = runner.invoke(cli.app, ["config", "check", "--config", str(config)])

    assert result.exit_code == 1
    assert "DEHYDRATER_KEY_DEHYDRATE" in result.output
    assert "DEHYDRATER_KEY_TRANSCRIBE" not in result.output


def test_key_set_stores_in_keychain(keychain: FakeKeychain) -> None:
    result = runner.invoke(cli.app, ["key", "set", "dehydrate"], input="secret\n")

    assert result.exit_code == 0, result.output
    assert keychain.entries == {"dehydrate": "secret"}
    assert "secret" not in result.output


def test_init_then_status(tmp_path: Path, config: Path, keychain: FakeKeychain) -> None:
    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"")
    workspace = tmp_path / "L01"

    init = runner.invoke(
        cli.app,
        ["init", str(workspace), "--recording", str(video), "--date", str(date(2026, 10, 12))],
    )
    status = runner.invoke(cli.app, ["status", str(workspace), "--config", str(config)])

    assert init.exit_code == 0, init.output
    assert status.exit_code == 0, status.output
    assert "extract_audio" in status.output
