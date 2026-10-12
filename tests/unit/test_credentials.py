from pathlib import Path

from dehydrater.credentials import SecretSource, SecretStore, env_var_name

from ..fakes import FakeKeychain


def test_env_var_name_is_derived_from_provider_name() -> None:
    assert env_var_name("write-sections") == "DEHYDRATER_KEY_WRITE_SECTIONS"


def test_lookup_order_is_env_then_dotenv_then_keychain(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("DEHYDRATER_KEY_CLEAN=from-dotenv\nDEHYDRATER_KEY_ASR=from-dotenv\n")
    store = SecretStore(
        env={"DEHYDRATER_KEY_CLEAN": "from-env"},
        dotenv_paths=[dotenv],
        keychain=FakeKeychain({"asr": "from-keychain", "notices": "from-keychain"}),
    )

    assert _source(store, "clean") == (SecretSource.ENV, "from-env")
    assert _source(store, "asr") == (SecretSource.DOTENV, "from-dotenv")
    assert _source(store, "notices") == (SecretSource.KEYCHAIN, "from-keychain")
    assert store.get("missing") is None


def test_empty_values_count_as_missing(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("DEHYDRATER_KEY_CLEAN=\n")
    store = SecretStore(env={}, dotenv_paths=[dotenv], keychain=FakeKeychain())

    assert store.get("clean") is None


def test_missing_dotenv_file_is_ignored(tmp_path: Path) -> None:
    store = SecretStore(env={}, dotenv_paths=[tmp_path / ".env"], keychain=FakeKeychain())

    assert store.get("clean") is None


def _source(store: SecretStore, provider: str) -> tuple[SecretSource, str] | None:
    secret = store.get(provider)
    return (secret.source, secret.value) if secret else None
