"""日志配置。界面上只显示简短的结论，排查问题所需的细节都写进日志文件。

- 全局日志：用户日志目录下的 dehydrater.log，记录所有命令，自动轮转
- 整理日志：每节课输出目录下的 cache/dehydrater.log，记录这节课每次整理的全过程

API Key 不会写入日志：本项目的代码从不记录它，httpx/httpcore 的日志也不包含请求头的值。
"""

import logging
import platform
import sys
from collections.abc import Generator
from contextlib import contextmanager
from importlib.metadata import version
from logging.handlers import RotatingFileHandler
from pathlib import Path

import platformdirs

from dehydrater.config import Field, Settings, Task

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
# httpcore 记录连接建立、请求体发送、响应读取等每一步，是排查网络中断的关键
_LOGGERS = ("dehydrater", "httpx", "httpcore")

logger = logging.getLogger(__name__)


def global_log_path() -> Path:
    return platformdirs.user_log_path("dehydrater") / "dehydrater.log"


def configure_logging() -> None:
    path = global_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    _attach(handler)
    logger.info(
        "启动 dehydrater %s · Python %s · %s · 参数 %s",
        version("dehydrater"),
        platform.python_version(),
        platform.platform(),
        sys.argv[1:],
    )


@contextmanager
def workspace_log(path: Path) -> Generator[None]:
    """在 with 块内把日志同时写到某节课的日志文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    _attach(handler)
    try:
        yield
    finally:
        for name in _LOGGERS:
            logging.getLogger(name).removeHandler(handler)
        handler.close()


def log_settings(settings: Settings) -> None:
    """记录每项设置的取值来源；API Key 只记录是否已设置。"""
    for task in Task:
        url, model, key = (settings.lookup(task, field) for field in Field)
        logger.info(
            "设置 %s：地址=%s（%s） 模型=%s（%s） Key=%s",
            task,
            url.value if url else "未设置",
            url.source if url else "-",
            model.value if model else "未设置",
            model.source if model else "-",
            f"已设置（{key.source}）" if key else "未设置",
        )


def _attach(handler: logging.Handler) -> None:
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.setLevel(logging.DEBUG)
    for name in _LOGGERS:
        named = logging.getLogger(name)
        named.setLevel(logging.DEBUG)
        named.addHandler(handler)
        # 不向根 logger 传播，避免被第三方库或 Python 默认配置打印到终端
        named.propagate = False
