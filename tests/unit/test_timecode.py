import pytest

from dehydrater.domain.timecode import format_timecode


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "00:00"), (59.9, "00:59"), (754, "12:34"), (3600, "1:00:00"), (3725, "1:02:05")],
)
def test_format_timecode(seconds: float, expected: str) -> None:
    assert format_timecode(seconds) == expected
