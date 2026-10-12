"""笔记：按大纲逐章并发撰写。以课件内容为主线，融入老师的口头讲解。

模型用 [@段落编号] 标注出自课堂讲解的内容，程序把它换成时间戳；不让模型编造时间。
"""

import asyncio
import re

from pydantic import BaseModel

from dehydrater.domain.notes import LectureNotes, NoteChapter, OutlineChapter
from dehydrater.domain.slides import Deck
from dehydrater.domain.timecode import format_timecode
from dehydrater.domain.transcript import Transcript, TranscriptSegment
from dehydrater.pipeline.artifacts import DECK, DEHYDRATED_TRANSCRIPT, LECTURE, NOTES, OUTLINE
from dehydrater.pipeline.memo import JsonMemo
from dehydrater.pipeline.stage import Stage, StageContext
from dehydrater.pipeline.structured import InvalidReplyError, complete_checked
from dehydrater.pipeline.templating import TemplateSet
from dehydrater.ports import ChatMessage, ChatModel, Fingerprint

_PROMPTS = ("notes.system.j2", "notes.user.j2")
_CITATION = re.compile(r"\[@(\d+)\]")
_CITATION_RUN = re.compile(r"(?:\[@\d+\])+")
"""紧挨着的多个引用，合并成一个时间戳标记。"""
_TOP_LEVEL_HEADING = re.compile(r"^#{1,2} ", re.MULTILINE)


class _Body(BaseModel):
    """块级缓存用的包装：缓存的是替换时间戳之前的原文。"""

    markdown: str


class WriteNotesStage(Stage):
    name = "write_notes"
    version = 3
    inputs = (LECTURE, DECK, DEHYDRATED_TRANSCRIPT, OUTLINE)
    outputs = (NOTES,)

    def __init__(self, chat: ChatModel, prompts: TemplateSet) -> None:
        self._chat = chat
        self._prompts = prompts

    def fingerprint(self) -> Fingerprint:
        return {**self._chat.fingerprint(), "prompts": self._prompts.digest(*_PROMPTS)}

    async def run(self, ctx: StageContext) -> None:
        deck = ctx.read(DECK)
        transcript = ctx.read(DEHYDRATED_TRANSCRIPT)
        outline = ctx.read(OUTLINE)
        memo = JsonMemo(ctx.files_dir / "chapters")
        done = 0

        async def write(chapter: OutlineChapter) -> NoteChapter:
            nonlocal done
            slides = deck.describe(*chapter.pages) if chapter.pages else None
            user_prompt = self._prompts.render(
                "notes.user.j2",
                lecture=ctx.read(LECTURE),
                chapter=chapter,
                slides=slides,
                pages=_pages_of(deck, chapter),
                paragraphs=_paragraphs_of(transcript, chapter),
            )
            body = await memo.get_or_compute(
                {"fingerprint": dict(self.fingerprint()), "prompt": user_prompt},
                _Body,
                lambda: self._ask(ctx, user_prompt, len(transcript.segments)),
            )
            done += 1
            ctx.report_progress(done, len(outline.chapters))
            return _to_chapter(chapter, slides, body.markdown, transcript)

        chapters = await asyncio.gather(*(write(chapter) for chapter in outline.chapters))
        ctx.write(
            NOTES,
            LectureNotes(
                overview=outline.overview,
                chapters=list(chapters),
                key_terms=outline.key_terms,
                notices=outline.notices,
            ),
        )

    async def _ask(self, ctx: StageContext, user_prompt: str, paragraph_count: int) -> _Body:
        messages = [
            ChatMessage("system", self._prompts.render("notes.system.j2")),
            ChatMessage("user", user_prompt),
        ]
        reply = await complete_checked(
            self._chat, messages, lambda text: _parse_body(text, paragraph_count)
        )
        ctx.record_usage(reply.usage)
        return reply.value


def _pages_of(deck: Deck, chapter: OutlineChapter) -> list[str]:
    if chapter.pages is None:
        return []
    first, last = chapter.pages
    return [page.text for page in deck.pages[first - 1 : last]]


def _paragraphs_of(
    transcript: Transcript, chapter: OutlineChapter
) -> list[tuple[int, TranscriptSegment]]:
    return [
        (index, transcript.segments[index])
        for r in chapter.paragraphs
        for index in range(r.first, r.last + 1)
    ]


def _parse_body(text: str, paragraph_count: int) -> _Body:
    body = text.strip()
    if _TOP_LEVEL_HEADING.search(body):
        raise InvalidReplyError("正文中不能使用一级或二级标题（# 或 ##），请从 ### 开始")
    if invalid := [n for n in map(int, _CITATION.findall(body)) if n >= paragraph_count]:
        raise InvalidReplyError(f"引用了不存在的段落 {invalid}，有效范围是 0–{paragraph_count - 1}")
    return _Body(markdown=body)


def _to_chapter(
    chapter: OutlineChapter, slides: str | None, body: str, transcript: Transcript
) -> NoteChapter:
    def timestamps(run: re.Match[str]) -> str:
        indices = sorted({int(index) for index in _CITATION.findall(run.group())})
        times = dict.fromkeys(format_timecode(transcript.segments[i].start) for i in indices)
        return f"`▶ {' · '.join(times)}`"

    starts = [transcript.segments[r.first].start for r in chapter.paragraphs]
    return NoteChapter(
        title=chapter.title,
        slides=slides,
        start=min(starts) if starts else None,
        body=_CITATION_RUN.sub(timestamps, body),
    )
