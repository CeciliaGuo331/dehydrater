"""密钥的查找与保存。

每个渠道一把密钥，以渠道名标识。查找顺序：
1. 环境变量 DEHYDRATER_KEY_<渠道名>
2. .env 文件中的同名变量（当前目录向上查找到的 .env，其次是配置目录下的 .env）
3. 系统钥匙串（macOS Keychain、Windows 凭据管理器、Linux Secret Service）
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from dotenv import dotenv_values

KEYCHAIN_SERVICE = "dehydrater"


class KeychainUnavailableError(Exception):
    pass


class Keychain(Protocol):
    def get(self, name: str) -> str | None:
        """钥匙串不可用时返回 None，不报错：它只是查找顺序中的最后一环。"""
        ...

    def set(self, name: str, value: str) -> None:
        """钥匙串不可用时抛出 KeychainUnavailableError。"""
        ...

    def delete(self, name: str) -> bool:
        """返回是否确实删除了一条记录。"""
        ...


class SecretSource(StrEnum):
    ENV = "环境变量"
    DOTENV = ".env"
    KEYCHAIN = "系统钥匙串"


@dataclass(frozen=True)
class Secret:
    value: str
    source: SecretSource
    location: str
    """具体来自哪里：变量名、.env 路径或钥匙串条目。"""


def env_var_name(provider: str) -> str:
    """渠道名到环境变量名的映射，例如 write-sections → DEHYDRATER_KEY_WRITE_SECTIONS。"""
    return "DEHYDRATER_KEY_" + re.sub(r"[^A-Za-z0-9]", "_", provider).upper()


class SecretStore:
    def __init__(
        self, env: Mapping[str, str], dotenv_paths: Sequence[Path], keychain: Keychain
    ) -> None:
        self._env = env
        self._dotenv = [(path, dotenv_values(path)) for path in dotenv_paths if path.is_file()]
        self._keychain = keychain

    def get(self, provider: str) -> Secret | None:
        name = env_var_name(provider)
        if value := self._env.get(name):
            return Secret(value, SecretSource.ENV, name)
        for path, values in self._dotenv:
            if value := values.get(name):
                return Secret(value, SecretSource.DOTENV, str(path))
        if value := self._keychain.get(provider):
            return Secret(value, SecretSource.KEYCHAIN, f"{KEYCHAIN_SERVICE}/{provider}")
        return None

    def save_to_keychain(self, provider: str, value: str) -> None:
        self._keychain.set(provider, value)

    def delete_from_keychain(self, provider: str) -> bool:
        return self._keychain.delete(provider)
