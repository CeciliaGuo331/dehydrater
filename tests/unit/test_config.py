import tomllib

import pytest
from pydantic import ValidationError

from dehydrater.config import AppConfig, example_config

_CLEAN_TASK = '[tasks.clean]\nprovider = "clean"'


def _example_with_clean_provider(provider: str) -> AppConfig:
    text = example_config()
    assert _CLEAN_TASK in text
    return AppConfig.model_validate(
        tomllib.loads(text.replace(_CLEAN_TASK, f'[tasks.clean]\nprovider = "{provider}"'))
    )


def test_example_config_is_valid() -> None:
    AppConfig.model_validate(tomllib.loads(example_config()))


def test_task_must_reference_existing_provider() -> None:
    with pytest.raises(ValidationError, match="不存在的渠道"):
        _example_with_clean_provider("nowhere")


def test_chat_task_cannot_use_asr_only_provider() -> None:
    with pytest.raises(ValidationError, match="chat"):
        _example_with_clean_provider("transcribe")


def test_used_providers_are_those_referenced_by_tasks() -> None:
    config = AppConfig.model_validate(tomllib.loads(example_config()))
    assert config.used_providers() == ["clean", "extract-notices", "transcribe", "write-sections"]


def test_provider_names_must_be_identifiers() -> None:
    text = example_config().replace("[providers.clean]", "[providers.Clean]")
    text = text.replace('provider = "clean"', 'provider = "Clean"')
    with pytest.raises(ValidationError, match="只能包含小写字母"):
        AppConfig.model_validate(tomllib.loads(text))
