import re
from datetime import date

# 依次尝试：2026-09-30、2026.09.30、2026_09_30、2026年9月30日、20260930
_PATTERNS = (
    re.compile(r"(?<!\d)(20\d{2})[-._](\d{1,2})[-._](\d{1,2})(?!\d)"),
    re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日"),
    re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)"),
)


def date_in_filename(name: str) -> date | None:
    """从文件名中找出上课日期；找不到或不是合法日期时返回 None。"""
    for pattern in _PATTERNS:
        for match in pattern.finditer(name):
            year, month, day = (int(part) for part in match.groups())
            try:
                return date(year, month, day)
            except ValueError:
                continue
    return None
