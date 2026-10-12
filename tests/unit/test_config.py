import tomllib

import pytest
from pydantic import ValidationError

from dehydrater.config import AppConfig, example_config

_CLEAN_TASK = '[tasks.clean]\nprovider = "volc-ark"'


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
        _example_with_clean_provider("volc-speech")


def test_missing_secrets_lists_only_unset_variables() -> None:
    config = AppConfig.model_validate(tomllib.loads(example_config()))
    assert config.missing_secrets({"ARK_API_KEY": "x", "VOLC_SPEECH_API_KEY": ""}) == [
        "VOLC_SPEECH_API_KEY"
    ]
