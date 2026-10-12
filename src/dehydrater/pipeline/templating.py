"""Jinja2 模板：LLM 提示词（prompts/）和 Markdown 输出（templates/）都放在独立文件里。"""

import hashlib

from jinja2 import Environment, PackageLoader, StrictUndefined

from dehydrater.domain.timecode import format_timecode


class TemplateSet:
    def __init__(self, directory: str) -> None:
        """directory 是 dehydrater 包内的子目录名。"""
        self._env = Environment(
            loader=PackageLoader("dehydrater", directory),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
            autoescape=False,
        )
        self._env.filters["timecode"] = format_timecode

    def render(self, name: str, **variables: object) -> str:
        return self._env.get_template(name).render(**variables)

    def digest(self, *names: str) -> str:
        """模板源码的摘要，放进阶段的 fingerprint：改了提示词，缓存就失效。"""
        digest = hashlib.sha256()
        for name in names:
            source, _, _ = self._env.loader.get_source(self._env, name)  # type: ignore[union-attr]
            digest.update(source.encode())
        return digest.hexdigest()
