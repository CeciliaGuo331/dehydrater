"""组合根：根据用户配置构造 adapters，注入到各阶段，组装成流水线。

这是唯一同时认识 pipeline 和 adapters 的模块。
"""

import os
from collections.abc import Callable
from pathlib import Path

from dotenv import find_dotenv

from dehydrater.adapters.asr_volcengine import VolcengineTranscriber
from dehydrater.adapters.audio_pyav import PyAVAudioExtractor
from dehydrater.adapters.llm_openai_compat import OpenAICompatibleChatModel
from dehydrater.adapters.slides_pymupdf import PyMuPDFSlideReader
from dehydrater.config import Settings, Task, user_env_file
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
from dehydrater.ports import AudioExtractor, ChatModel, Transcriber

# 方舟的豆包模型默认开启深度思考：一句话的回答要 40 秒、上千个推理 token，本项目的任务都不需要
_ARK_HOST = "ark.cn-beijing.volces.com"
_ARK_EXTRA_BODY = {"thinking": {"type": "disabled"}}
_LLM_CONCURRENCY = 4


def load_settings() -> Settings:
    """环境变量 → 当前目录向上找到的 .env → 用户配置目录下的 env 文件。"""
    env_files = [Path(found)] if (found := find_dotenv(usecwd=True)) else []
    env_files.append(user_env_file())
    return Settings(os.environ, env_files)


def build_transcriber(settings: Settings) -> VolcengineTranscriber:
    task = settings.task(Task.TRANSCRIBE)
    return VolcengineTranscriber(base_url=task.url, api_key=task.key, resource_id=task.model)


def build_chat_model(settings: Settings, task_name: Task) -> OpenAICompatibleChatModel:
    task = settings.task(task_name)
    return OpenAICompatibleChatModel(
        base_url=task.url,
        api_key=task.key,
        model=task.model,
        temperature=None,
        max_tokens=None,
        extra_body=_ARK_EXTRA_BODY if _ARK_HOST in task.url else {},
        max_concurrency=_LLM_CONCURRENCY,
    )


def build_media_probe() -> AudioExtractor:
    return PyAVAudioExtractor()


def build_verifier(settings: Settings, task: Task) -> Transcriber | ChatModel:
    if task == Task.TRANSCRIBE:
        return build_transcriber(settings)
    return build_chat_model(settings, task)


def build_stages(settings: Settings) -> list[Stage]:
    """按依赖顺序排列的全部阶段。"""
    prompts = TemplateSet("prompts")
    templates = TemplateSet("templates")
    return [
        ExtractAudioStage(PyAVAudioExtractor()),
        IngestSlidesStage(PyMuPDFSlideReader()),
        TranscribeStage(build_transcriber(settings)),
        RenderRawStage(templates),
        DehydrateStage(build_chat_model(settings, Task.DEHYDRATE), prompts),
        RenderDehydratedStage(templates),
        OutlineStage(build_chat_model(settings, Task.OUTLINE), prompts),
        WriteNotesStage(build_chat_model(settings, Task.WRITE_NOTES), prompts),
        RenderNotesStage(templates),
    ]


def build_pipeline(
    workspace: Workspace,
    settings: Settings,
    on_event: Callable[[PipelineEvent], None] = lambda _: None,
) -> LecturePipeline:
    return LecturePipeline(workspace, build_stages(settings), on_event)
