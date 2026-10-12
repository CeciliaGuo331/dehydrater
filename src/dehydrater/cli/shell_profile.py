"""把设置写进 shell 的启动文件，或生成可以手动粘贴的片段。

写入的内容放在标记行之间；再次运行 setup 时替换这一段，不会重复追加。
"""

import os
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_BEGIN = "# >>> dehydrater >>>"
_END = "# <<< dehydrater <<<"


@dataclass(frozen=True)
class ShellProfile:
    name: str
    path: Path | None
    """启动文件；None 表示无法自动写入，只能显示片段。"""

    def snippet(self, variables: Mapping[str, str]) -> str:
        lines = [_assignment(self.name, key, value) for key, value in variables.items()]
        return "\n".join([_BEGIN, *lines, _END])

    def install(self, variables: Mapping[str, str]) -> None:
        assert self.path is not None
        block = self.snippet(variables)
        current = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        if _BEGIN in current and _END in current:
            before, rest = current.split(_BEGIN, 1)
            after = rest.split(_END, 1)[1]
            updated = f"{before}{block}{after}"
        else:
            updated = f"{current.rstrip()}\n\n{block}\n" if current.strip() else f"{block}\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(updated, encoding="utf-8")


def detect_shell(
    env: Mapping[str, str] = os.environ, home: Path | None = None, os_name: str = os.name
) -> ShellProfile:
    home = home or Path.home()
    if os_name == "nt":
        return ShellProfile("powershell", None)
    name = Path(env.get("SHELL", "")).name
    match name:
        case "zsh":
            return ShellProfile(name, home / ".zshrc")
        case "bash":
            return ShellProfile(name, home / ".bashrc")
        case "fish":
            return ShellProfile(name, home / ".config" / "fish" / "config.fish")
        case _:
            return ShellProfile(name or "sh", None)


def write_env_file(path: Path, variables: Mapping[str, str]) -> None:
    """写成 .env 格式，权限设为仅本人可读写（文件中有 API Key）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{key}={shlex.quote(value)}\n" for key, value in variables.items()),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _assignment(shell: str, key: str, value: str) -> str:
    match shell:
        case "fish":
            return f"set -gx {key} {shlex.quote(value)}"
        case "powershell":
            return f'$env:{key} = "{value}"'
        case _:
            return f"export {key}={shlex.quote(value)}"
