from datetime import date

import pytest

from dehydrater.domain.dates import date_in_filename


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("操作系统 - 2026-09-30第3-4节 - 陈向群.ts", date(2026, 9, 30)),
        ("lecture_2026.10.12.mp4", date(2026, 10, 12)),
        ("2026年9月3日 操作系统.m4a", date(2026, 9, 3)),
        ("OS20261012.mp3", date(2026, 10, 12)),
        ("第3讲.mp4", None),
        ("2026-13-40.mp4", None),
    ],
)
def test_date_in_filename(name: str, expected: date | None) -> None:
    assert date_in_filename(name) == expected
