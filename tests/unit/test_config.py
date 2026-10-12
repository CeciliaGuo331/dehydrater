from pathlib import Path

from dehydrater.config import Field, Settings, Task, env_name


def test_env_name() -> None:
    assert env_name(Task.WRITE_NOTES, Field.KEY) == "DEHYDRATER_WRITE_NOTES_KEY"


def test_lookup_order_is_env_then_files_then_default(tmp_path: Path) -> None:
    project_env = tmp_path / ".env"
    project_env.write_text(
        "DEHYDRATER_DEHYDRATE_KEY=from-project\nDEHYDRATER_OUTLINE_KEY=from-project\n"
    )
    user_env = tmp_path / "env"
    user_env.write_text("DEHYDRATER_OUTLINE_KEY=from-user\nDEHYDRATER_OUTLINE_MODEL=ep-123\n")
    settings = Settings({"DEHYDRATER_DEHYDRATE_KEY": "from-env"}, [project_env, user_env])

    assert settings.task(Task.DEHYDRATE).key == "from-env"
    assert settings.task(Task.OUTLINE).key == "from-project"
    assert settings.task(Task.OUTLINE).model == "ep-123"
    assert settings.lookup(Task.OUTLINE, Field.URL).source == "默认值"  # type: ignore[union-attr]


def test_keys_have_no_default_and_empty_counts_as_missing(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DEHYDRATER_TRANSCRIBE_KEY=\n")

    settings = Settings({}, [env_file, tmp_path / "missing-file"])

    assert settings.missing() == [env_name(task, Field.KEY) for task in Task]
