from dehydrater.domain.base import Seconds


def format_timecode(at: Seconds) -> str:
    """把秒数格式化为 mm:ss，超过一小时为 h:mm:ss。"""
    total = int(at)
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
