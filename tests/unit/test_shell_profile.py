import sys
from pathlib import Path

from dehydrater.cli.shell_profile import ShellProfile, detect_shell, write_env_file

_VARIABLES = {"DEHYDRATER_DEHYDRATE_KEY": "k 1", "DEHYDRATER_DEHYDRATE_MODEL": "ep-1"}


def test_detects_shell_profile(tmp_path: Path) -> None:
    def detect(shell: str) -> Path | None:
        return detect_shell({"SHELL": shell}, tmp_path, os_name="posix").path

    assert detect("/usr/bin/zsh") == tmp_path / ".zshrc"
    assert detect("/bin/fish") == tmp_path / ".config/fish/config.fish"
    assert detect("/bin/tcsh") is None
    assert detect_shell({}, tmp_path, os_name="nt").name == "powershell"


def test_snippet_syntax_per_shell() -> None:
    assert "export DEHYDRATER_DEHYDRATE_KEY='k 1'" in ShellProfile("bash", None).snippet(_VARIABLES)
    assert "set -gx DEHYDRATER_DEHYDRATE_KEY 'k 1'" in ShellProfile("fish", None).snippet(
        _VARIABLES
    )


def test_install_replaces_previous_block(tmp_path: Path) -> None:
    rc = tmp_path / ".zshrc"
    rc.write_text("alias ll='ls -l'\n")
    profile = ShellProfile("zsh", rc)

    profile.install(_VARIABLES)
    profile.install({"DEHYDRATER_DEHYDRATE_KEY": "new"})

    text = rc.read_text()
    assert text.startswith("alias ll='ls -l'\n")
    assert text.count("# >>> dehydrater >>>") == 1
    assert "DEHYDRATER_DEHYDRATE_KEY=new" in text
    assert "ep-1" not in text


def test_env_file_is_private(tmp_path: Path) -> None:
    path = tmp_path / "dehydrater" / "env"

    write_env_file(path, _VARIABLES)

    if sys.platform != "win32":  # Windows 上 chmod 只能控制只读，权限位没有意义
        assert path.stat().st_mode & 0o777 == 0o600
    assert "DEHYDRATER_DEHYDRATE_KEY='k 1'" in path.read_text()
