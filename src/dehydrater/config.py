"""用户配置：渠道（怎么连某个 API 账号）与任务（每一步用哪个渠道、哪个模型）。"""

import os
import tomllib
from collections.abc import Mapping
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
    api_key_env: str


class VolcengineAsrProvider(_Strict):
    capabilities: ClassVar[frozenset[Capability]] = frozenset({Capability.ASR})

    kind: Literal["volcengine-asr"]
    api_key_env: str
    """新版控制台的 API Key，对应请求头 X-Api-Key。"""


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


class AppConfig(_Strict):
    providers: dict[str, ProviderConfig]
    tasks: TasksConfig

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

    def missing_secrets(self, env: Mapping[str, str] = os.environ) -> list[str]:
        """任务用到的渠道中，尚未设置的密钥环境变量。"""
        used = {task.provider for task, _ in self.tasks.required_capabilities().values()}
        return sorted(
            {self.providers[name].api_key_env for name in used}
            - {key for key, value in env.items() if value}
        )


def default_config_path() -> Path:
    return platformdirs.user_config_path("dehydrater") / "config.toml"


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
