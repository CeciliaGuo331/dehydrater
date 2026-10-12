"""组合根：根据配置构造 adapters，注入到各阶段，组装成流水线。

这是唯一同时认识 pipeline 和 adapters 的模块。
"""

import os
from collections.abc import Callable, Mapping

from dehydrater.adapters.asr_openai_compat import OpenAICompatibleTranscriber
from dehydrater.adapters.asr_volcengine import VolcengineTranscriber
from dehydrater.adapters.audio_pyav import PyAVAudioExtractor
from dehydrater.adapters.llm_openai_compat import OpenAICompatibleChatModel
from dehydrater.adapters.slides_pymupdf import PyMuPDFSlideReader
from dehydrater.config import (
    AppConfig,
    OpenAICompatibleProvider,
    TaskConfig,
    VolcengineAsrProvider,
)
from dehydrater.pipeline.events import PipelineEvent
from dehydrater.pipeline.lecture import LecturePipeline
from dehydrater.pipeline.stage import Stage
from dehydrater.pipeline.stages.align import AlignStage
from dehydrater.pipeline.stages.clean import CleanStage
from dehydrater.pipeline.stages.extract_audio import ExtractAudioStage
from dehydrater.pipeline.stages.extract_notices import ExtractNoticesStage
from dehydrater.pipeline.stages.ingest_slides import IngestSlidesStage
from dehydrater.pipeline.stages.render import (
    RenderLectureStage,
    RenderNoticesStage,
    RenderTranscriptStage,
)
from dehydrater.pipeline.stages.transcribe import TranscribeStage
from dehydrater.pipeline.stages.write_sections import WriteSectionsStage
from dehydrater.pipeline.workspace import Workspace
from dehydrater.ports import ChatModel, Transcriber


class _Adapters:
    """按任务配置构造 adapter。"""

    def __init__(self, config: AppConfig, env: Mapping[str, str]) -> None:
        self._config = config
        self._env = env

    def transcriber(self, task: TaskConfig) -> Transcriber:
        match self._config.provider_of(task):
            case OpenAICompatibleProvider(base_url=base_url, api_key_env=key_env):
                return OpenAICompatibleTranscriber(
                    base_url=base_url, api_key=self._secret(key_env), model=task.model
                )
            case VolcengineAsrProvider(api_key_env=key_env):
                return VolcengineTranscriber(api_key=self._secret(key_env), resource_id=task.model)

    def chat_model(self, task: TaskConfig) -> ChatModel:
        provider = self._config.provider_of(task)
        # 配置校验已保证 CHAT 任务只会配到支持 CHAT 的渠道
        assert isinstance(provider, OpenAICompatibleProvider)
        return OpenAICompatibleChatModel(
            base_url=provider.base_url,
            api_key=self._secret(provider.api_key_env),
            model=task.model,
            temperature=task.temperature,
        )

    def _secret(self, env_name: str) -> str:
        # 缺失的密钥由 CLI 在运行前统一检查；这里允许为空，便于 status 等命令使用
        return self._env.get(env_name, "")


def build_stages(config: AppConfig, env: Mapping[str, str] = os.environ) -> list[Stage]:
    """按依赖顺序排列的全部阶段。"""
    adapters = _Adapters(config, env)
    tasks = config.tasks
    return [
        ExtractAudioStage(PyAVAudioExtractor()),
        IngestSlidesStage(PyMuPDFSlideReader()),
        TranscribeStage(adapters.transcriber(tasks.transcribe)),
        ExtractNoticesStage(adapters.chat_model(tasks.extract_notices)),
        RenderNoticesStage(),
        CleanStage(adapters.chat_model(tasks.clean)),
        RenderTranscriptStage(),
        AlignStage(),
        WriteSectionsStage(adapters.chat_model(tasks.write_sections)),
        RenderLectureStage(),
    ]


def build_pipeline(
    workspace: Workspace,
    config: AppConfig,
    on_event: Callable[[PipelineEvent], None] = lambda _: None,
) -> LecturePipeline:
    return LecturePipeline(workspace, build_stages(config), on_event)
