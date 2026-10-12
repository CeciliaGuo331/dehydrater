import tomllib

import pytest
from pydantic import ValidationError

from dehydrater.config import AppConfig, example_config

_TASK = '[tasks.dehydrate]\nprovider = "dehydrate"'


def _example_with_dehydrate_provider(provider: str) -> AppConfig:
    text = example_config()
    assert _TASK in text
    return AppConfig.model_validate(
        tomllib.loads(text.replace(_TASK, f'[tasks.dehydrate]\nprovider = "{provider}"'))
    )


def test_example_config_is_valid() -> None:
    AppConfig.model_validate(tomllib.loads(example_config()))


def test_task_must_reference_existing_provider() -> None:
    with pytest.raises(ValidationError, match="不存在的渠道"):
        _example_with_dehydrate_provider("nowhere")


def test_chat_task_cannot_use_asr_only_provider() -> None:
    with pytest.raises(ValidationError, match="chat"):
        _example_with_dehydrate_provider("transcribe")


def test_used_providers_are_those_referenced_by_tasks() -> None:
    config = AppConfig.model_validate(tomllib.loads(example_config()))
    assert config.used_providers() == ["dehydrate", "guide", "transcribe"]


def test_provider_names_must_be_identifiers() -> None:
    text = example_config().replace("[providers.guide]", "[providers.Guide]")
    text = text.replace('provider = "guide"', 'provider = "Guide"')
    with pytest.raises(ValidationError, match="只能包含小写字母"):
        AppConfig.model_validate(tomllib.loads(text))
