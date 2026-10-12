"""组合根：根据配置构造 adapters，注入到各阶段，组装成流水线。

这是唯一同时认识 pipeline 和 adapters 的模块。
"""

import os
from collections.abc import Callable
from pathlib import Path

from dotenv import find_dotenv

from dehydrater.adapters.asr_openai_compat import OpenAICompatibleTranscriber
from dehydrater.adapters.asr_volcengine import VolcengineApi, VolcengineTranscriber
from dehydrater.adapters.audio_pyav import PyAVAudioExtractor
from dehydrater.adapters.keychain_keyring import SystemKeychain
from dehydrater.adapters.llm_openai_compat import OpenAICompatibleChatModel
from dehydrater.adapters.slides_pymupdf import PyMuPDFSlideReader
from dehydrater.config import (
    AppConfig,
    OpenAICompatibleProvider,
    TaskConfig,
    VolcengineAsrProvider,
    config_dir,
)
from dehydrater.credentials import SecretStore
from dehydrater.pipeline.events import PipelineEvent
from dehydrater.pipeline.lecture import LecturePipeline
from dehydrater.pipeline.stage import Stage
from dehydrater.pipeline.stages.dehydrate import DehydrateStage
from dehydrater.pipeline.stages.extract_audio import ExtractAudioStage
from dehydrater.pipeline.stages.ingest_slides import IngestSlidesStage
from dehydrater.pipeline.stages.outline import OutlineStage
from dehydrater.pipeline.stages.render import (
    RenderDehydratedStage,
    RenderNotesStage,
    RenderRawStage,
)
from dehydrater.pipeline.stages.transcribe import TranscribeStage
from dehydrater.pipeline.stages.write_notes import WriteNotesStage
from dehydrater.pipeline.templating import TemplateSet
from dehydrater.pipeline.workspace import Workspace
from dehydrater.ports import ChatModel, Transcriber


class _Adapters:
    """按任务配置构造 adapter。"""

    def __init__(self, config: AppConfig, secrets: SecretStore) -> None:
        self._config = config
        self._secrets = secrets

    def transcriber(self, task: TaskConfig) -> Transcriber:
        match self._config.provider_of(task):
            case OpenAICompatibleProvider(base_url=base_url):
                return OpenAICompatibleTranscriber(
                    base_url=base_url, api_key=self._secret(task), model=task.model
                )
            case VolcengineAsrProvider(api=api):
                return VolcengineTranscriber(
                    api_key=self._secret(task), resource_id=task.model, api=VolcengineApi(api)
                )

    def chat_model(self, task: TaskConfig) -> ChatModel:
        provider = self._config.provider_of(task)
        # 配置校验已保证 CHAT 任务只会配到支持 CHAT 的渠道
        assert isinstance(provider, OpenAICompatibleProvider)
        return OpenAICompatibleChatModel(
            base_url=provider.base_url,
            api_key=self._secret(task),
            model=task.model,
            temperature=task.temperature,
            max_tokens=task.max_tokens,
            extra_body=task.extra_body,
            max_concurrency=provider.max_concurrency,
        )

    def _secret(self, task: TaskConfig) -> str:
        # 缺失的密钥由 CLI 在运行前用 missing_keys 统一检查；这里允许为空，便于 status 等命令使用
        secret = self._secrets.get(task.provider)
        return secret.value if secret else ""


def build_secret_store() -> SecretStore:
    """环境变量 → 当前目录向上找到的 .env → 配置目录下的 .env → 系统钥匙串。"""
    dotenv_paths = [Path(found)] if (found := find_dotenv(usecwd=True)) else []
    dotenv_paths.append(config_dir() / ".env")
    return SecretStore(os.environ, dotenv_paths, SystemKeychain())


def missing_keys(config: AppConfig, secrets: SecretStore) -> list[str]:
    """任务用到、但哪里都找不到密钥的渠道。"""
    return [name for name in config.used_providers() if secrets.get(name) is None]


def build_stages(config: AppConfig, secrets: SecretStore) -> list[Stage]:
    """按依赖顺序排列的全部阶段。"""
    adapters = _Adapters(config, secrets)
    tasks = config.tasks
    prompts = TemplateSet("prompts")
    templates = TemplateSet("templates")
    return [
        ExtractAudioStage(PyAVAudioExtractor()),
        IngestSlidesStage(PyMuPDFSlideReader()),
        TranscribeStage(adapters.transcriber(tasks.transcribe)),
        RenderRawStage(templates),
        DehydrateStage(adapters.chat_model(tasks.dehydrate), prompts),
        RenderDehydratedStage(templates),
        OutlineStage(adapters.chat_model(tasks.outline), prompts),
        WriteNotesStage(adapters.chat_model(tasks.write_notes), prompts),
        RenderNotesStage(templates),
    ]


def build_pipeline(
    workspace: Workspace,
    config: AppConfig,
    secrets: SecretStore,
    on_event: Callable[[PipelineEvent], None] = lambda _: None,
) -> LecturePipeline:
    return LecturePipeline(workspace, build_stages(config, secrets), on_event)
