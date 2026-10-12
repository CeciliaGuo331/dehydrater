"""大纲：通读课件和脱水逐字稿，把整节课分成章，并给出概览、术语和课堂通知。

每章对应一段课件页码和若干讲课段落，相当于让模型完成"讲解对齐到课件"。
模型只引用页码和段落编号，时间由编号换算。
"""

from pydantic import BaseModel

from dehydrater.domain.notes import Notice, Outline, OutlineChapter, ParagraphRange, Term
from dehydrater.domain.slides import Deck
from dehydrater.domain.transcript import Transcript
from dehydrater.pipeline.artifacts import DECK, DEHYDRATED_TRANSCRIPT, LECTURE, OUTLINE
from dehydrater.pipeline.stage import Stage, StageContext
from dehydrater.pipeline.structured import InvalidReplyError, complete_json
from dehydrater.pipeline.templating import TemplateSet
from dehydrater.ports import ChatMessage, ChatModel, Fingerprint

_PROMPTS = ("outline.system.j2", "outline.user.j2")
# 低于这个比例的讲课段落被分配到章节中，就要求模型重做：没分配的段落不会进入笔记
_MIN_COVERAGE = 0.9


class _Range(BaseModel):
    first: int
    last: int


class _Chapter(BaseModel):
    title: str
    first_page: int | None
    last_page: int | None
    paragraphs: list[_Range]


class _Term(BaseModel):
    term: str
    explanation: str


class _Notice(BaseModel):
    text: str
    paragraph: int


class _Reply(BaseModel):
    overview: str
    chapters: list[_Chapter]
    key_terms: list[_Term]
    notices: list[_Notice]


class OutlineStage(Stage):
    name = "outline"
    inputs = (LECTURE, DECK, DEHYDRATED_TRANSCRIPT)
    outputs = (OUTLINE,)

    def __init__(self, chat: ChatModel, prompts: TemplateSet) -> None:
        self._chat = chat
        self._prompts = prompts

    def fingerprint(self) -> Fingerprint:
        return {**self._chat.fingerprint(), "prompts": self._prompts.digest(*_PROMPTS)}

    async def run(self, ctx: StageContext) -> None:
        deck = ctx.read(DECK)
        transcript = ctx.read(DEHYDRATED_TRANSCRIPT)
        messages = [
            ChatMessage(
                "system", self._prompts.render("outline.system.j2", has_slides=bool(deck.pages))
            ),
            ChatMessage(
                "user",
                self._prompts.render(
                    "outline.user.j2",
                    lecture=ctx.read(LECTURE),
                    pages=deck.pages,
                    paragraphs=transcript.segments,
                ),
            ),
        ]
        reply = await complete_json(
            self._chat, messages, _Reply, check=lambda r: _check(r, deck, transcript)
        )
        ctx.record_usage(reply.usage)
        ctx.write(OUTLINE, _to_outline(reply.value, transcript))


def _check(reply: _Reply, deck: Deck, transcript: Transcript) -> None:
    page_count, paragraph_count = len(deck.pages), len(transcript.segments)
    problems: list[str] = []
    for chapter in reply.chapters:
        pages = (chapter.first_page, chapter.last_page)
        if pages != (None, None) and not (
            pages[0] is not None
            and pages[1] is not None
            and 1 <= pages[0] <= pages[1] <= page_count
        ):
            problems.append(
                f"章节「{chapter.title}」的页码 {pages} 无效，有效范围是 1–{page_count}"
            )
        if paragraph_count and not chapter.paragraphs:
            problems.append(f"章节「{chapter.title}」没有对应的讲课段落；没讲到的课件页不要建章")
        for r in chapter.paragraphs:
            if not 0 <= r.first <= r.last < paragraph_count:
                problems.append(f"章节「{chapter.title}」的段落范围 [{r.first}, {r.last}] 无效")
    for notice in reply.notices:
        if not 0 <= notice.paragraph < paragraph_count:
            problems.append(f"通知「{notice.text}」的段落编号 {notice.paragraph} 无效")
    if problems:
        raise InvalidReplyError("\n".join(problems))

    assigned = {i for c in reply.chapters for r in c.paragraphs for i in range(r.first, r.last + 1)}
    if paragraph_count and len(assigned) / paragraph_count < _MIN_COVERAGE:
        missing = sorted(set(range(paragraph_count)) - assigned)
        raise InvalidReplyError(
            f"以下段落没有分配给任何章节：{missing}。每个有内容的段落都要归入某一章"
        )


def _to_outline(reply: _Reply, transcript: Transcript) -> Outline:
    return Outline(
        overview=reply.overview,
        chapters=[
            OutlineChapter(
                title=chapter.title,
                pages=(chapter.first_page, chapter.last_page)
                if chapter.first_page is not None and chapter.last_page is not None
                else None,
                paragraphs=[ParagraphRange(first=r.first, last=r.last) for r in chapter.paragraphs],
            )
            for chapter in reply.chapters
        ],
        key_terms=[Term(term=t.term, explanation=t.explanation) for t in reply.key_terms],
        notices=[
            Notice(text=n.text, at=transcript.segments[n.paragraph].start) for n in reply.notices
        ],
    )
