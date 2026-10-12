"""用户配置：渠道（怎么连某个 API 账号）与任务（每一步用哪个渠道、哪个模型）。"""

import re
import tomllib
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Annotated, ClassVar, Literal

import platformdirs
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ConfigError(Exception):
    pass


class Capability(StrEnum):
    ASR = "asr"
    CHAT = "chat"


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OpenAICompatibleProvider(_Strict):
    capabilities: ClassVar[frozenset[Capability]] = frozenset({Capability.ASR, Capability.CHAT})

    kind: Literal["openai-compatible"]
    base_url: str


class VolcengineAsrProvider(_Strict):
    capabilities: ClassVar[frozenset[Capability]] = frozenset({Capability.ASR})

    kind: Literal["volcengine-asr"]
    api: Literal["standard", "flash"] = "standard"
    """standard：提交任务后轮询；flash：极速版，同步返回。两者资源 ID 不同，需分别开通。"""


type ProviderConfig = Annotated[
    OpenAICompatibleProvider | VolcengineAsrProvider, Field(discriminator="kind")
]


class TaskConfig(_Strict):
    provider: str
    model: str
    """LLM 的模型名；火山 ASR 则为资源 ID，例如 volc.seedasr.auc。"""
    temperature: float | None = None


class TasksConfig(_Strict):
    transcribe: TaskConfig
    clean: TaskConfig
    extract_notices: TaskConfig
    write_sections: TaskConfig

    def required_capabilities(self) -> dict[str, tuple[TaskConfig, Capability]]:
        return {
            "transcribe": (self.transcribe, Capability.ASR),
            "clean": (self.clean, Capability.CHAT),
            "extract_notices": (self.extract_notices, Capability.CHAT),
            "write_sections": (self.write_sections, Capability.CHAT),
        }


_PROVIDER_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")


class AppConfig(_Strict):
    providers: dict[str, ProviderConfig]
    """渠道名 → 渠道配置。渠道名同时用来查找该渠道的密钥，见 credentials.py。"""
    tasks: TasksConfig

    @model_validator(mode="after")
    def _provider_names_are_identifiers(self) -> "AppConfig":
        for name in self.providers:
            if not _PROVIDER_NAME.fullmatch(name):
                raise ValueError(f"渠道名 {name!r} 只能包含小写字母、数字、- 和 _")
        return self

    @model_validator(mode="after")
    def _tasks_reference_capable_providers(self) -> "AppConfig":
        for task_name, (task, capability) in self.tasks.required_capabilities().items():
            provider = self.providers.get(task.provider)
            if provider is None:
                raise ValueError(f"任务 {task_name} 引用了不存在的渠道 {task.provider!r}")
            if capability not in provider.capabilities:
                raise ValueError(
                    f"任务 {task_name} 需要 {capability} 能力，"
                    f"但渠道 {task.provider!r}（{provider.kind}）不支持"
                )
        return self

    def provider_of(self, task: TaskConfig) -> ProviderConfig:
        return self.providers[task.provider]

    def used_providers(self) -> list[str]:
        """被任务引用到的渠道名。"""
        return sorted({task.provider for task, _ in self.tasks.required_capabilities().values()})


def config_dir() -> Path:
    return platformdirs.user_config_path("dehydrater")


def default_config_path() -> Path:
    return config_dir() / "config.toml"


def example_config() -> str:
    return resources.files("dehydrater").joinpath("config.example.toml").read_text("utf-8")


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        raise ConfigError(f"找不到配置文件 {path}，可以先运行 `dehydrater config init`")
    try:
        with path.open("rb") as f:
            return AppConfig.model_validate(tomllib.load(f))
    except (tomllib.TOMLDecodeError, ValidationError) as error:
        raise ConfigError(f"配置文件 {path} 有误：\n{error}") from error
