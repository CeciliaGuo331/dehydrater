"""用户配置：每个调用 API 的任务各有三项设置——接入地址、模型、API Key。

每项设置按以下顺序查找，先找到的生效：
1. 环境变量，例如 DEHYDRATER_DEHYDRATE_KEY
2. 当前目录向上找到的第一个 .env 文件
3. 用户配置目录下的 env 文件（`dehydrater setup` 可以写入这里）
4. 内置默认值（只有地址和模型有默认值，API Key 必须由用户提供）
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import platformdirs
from dotenv import dotenv_values

_ASR_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel"
_ARK_URL = "https://ark.cn-beijing.volces.com/api/v3"


class Task(StrEnum):
    TRANSCRIBE = "transcribe"
    DEHYDRATE = "dehydrate"
    OUTLINE = "outline"
    WRITE_NOTES = "write_notes"

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    Task.TRANSCRIBE: "录音文件识别",
    Task.DEHYDRATE: "逐字稿脱水",
    Task.OUTLINE: "笔记大纲",
    Task.WRITE_NOTES: "笔记撰写",
}


class Field(StrEnum):
    URL = "url"
    MODEL = "model"
    KEY = "key"


_DEFAULTS: dict[tuple[Task, Field], str] = {
    (Task.TRANSCRIBE, Field.URL): _ASR_URL,
    (Task.TRANSCRIBE, Field.MODEL): "volc.seedasr.auc",
    (Task.DEHYDRATE, Field.URL): _ARK_URL,
    (Task.DEHYDRATE, Field.MODEL): "doubao-seed-2-1-lite-260915",
    (Task.OUTLINE, Field.URL): _ARK_URL,
    (Task.OUTLINE, Field.MODEL): "doubao-seed-2-1-pro-260915",
    (Task.WRITE_NOTES, Field.URL): _ARK_URL,
    (Task.WRITE_NOTES, Field.MODEL): "doubao-seed-2-1-pro-260915",
}


def env_name(task: Task, field: Field) -> str:
    return f"DEHYDRATER_{task.upper()}_{field.upper()}"


def default_value(task: Task, field: Field) -> str | None:
    return _DEFAULTS.get((task, field))


def config_dir() -> Path:
    return platformdirs.user_config_path("dehydrater")


def user_env_file() -> Path:
    return config_dir() / "env"


@dataclass(frozen=True)
class Setting:
    value: str
    source: str
    """人可读的来源：环境变量、某个文件路径或"默认值"。"""


@dataclass(frozen=True)
class TaskSettings:
    url: str
    model: str
    key: str


class Settings:
    def __init__(self, env: Mapping[str, str], env_files: Sequence[Path]) -> None:
        self._layers: list[tuple[str, Mapping[str, str | None]]] = [("环境变量", env)]
        self._layers += [(str(path), dotenv_values(path)) for path in env_files if path.is_file()]

    def lookup(self, task: Task, field: Field) -> Setting | None:
        name = env_name(task, field)
        for source, values in self._layers:
            if value := values.get(name):
                return Setting(value, source)
        if default := default_value(task, field):
            return Setting(default, "默认值")
        return None

    def task(self, task: Task) -> TaskSettings:
        """缺失的项为空字符串；调用方应先用 missing() 检查。"""

        def value(field: Field) -> str:
            setting = self.lookup(task, field)
            return setting.value if setting else ""

        return TaskSettings(url=value(Field.URL), model=value(Field.MODEL), key=value(Field.KEY))

    def missing(self) -> list[str]:
        """还没有设置的项，以环境变量名表示。"""
        return [
            env_name(task, field)
            for task in Task
            for field in Field
            if self.lookup(task, field) is None
        ]
