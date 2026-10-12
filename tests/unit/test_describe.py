import httpx

from dehydrater.cli.display import describe


def test_timeout_without_message_is_explained() -> None:
    assert describe(httpx.ReadTimeout("")).startswith("网络超时（ReadTimeout）")


def test_plain_errors_keep_their_message() -> None:
    assert describe(ValueError("坏了")) == "坏了"
    assert describe(RuntimeError()) == "RuntimeError"
