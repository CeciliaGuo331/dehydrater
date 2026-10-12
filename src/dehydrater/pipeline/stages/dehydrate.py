"""脱水：分块交给 LLM，把啰嗦的口语讲解改写成简洁的书面文字，保留全部信息点。

LLM 只返回"哪几句合并成一段、改写后的文字"，时间戳从原始分句推出，不让模型编造时间。
"""

import asyncio

from pydantic import BaseModel

from dehydrater.domain.chunking import chunk_segments
from dehydrater.domain.transcript import Transcript, TranscriptSegment
from dehydrater.pipeline.artifacts import DEHYDRATED_TRANSCRIPT, RAW_TRANSCRIPT
from dehydrater.pipeline.memo import JsonMemo
from dehydrater.pipeline.stage import Stage, StageContext
from dehydrater.pipeline.structured import InvalidReplyError, complete_json
from dehydrater.pipeline.templating import TemplateSet
from dehydrater.ports import ChatMessage, ChatModel, Fingerprint

_PROMPTS = ("dehydrate.system.j2", "dehydrate.user.j2")
_CHUNK_CHARS = 2500
# 预期脱水后剩原文的三分之一左右；超出这个区间多半是删过头或者没脱水
_KEPT_RATIO_RANGE = (0.15, 0.6)


class _Paragraph(BaseModel):
    first: int
    last: int
    text: str


class _Reply(BaseModel):
    paragraphs: list[_Paragraph]


class DehydrateStage(Stage):
    name = "dehydrate"
    inputs = (RAW_TRANSCRIPT,)
    outputs = (DEHYDRATED_TRANSCRIPT,)

    def __init__(self, chat: ChatModel, prompts: TemplateSet) -> None:
        self._chat = chat
        self._prompts = prompts

    def fingerprint(self) -> Fingerprint:
        return {
            **self._chat.fingerprint(),
            "prompts": self._prompts.digest(*_PROMPTS),
            "chunk_chars": _CHUNK_CHARS,
        }

    async def run(self, ctx: StageContext) -> None:
        raw = ctx.read(RAW_TRANSCRIPT)
        chunks = chunk_segments(raw.segments, _CHUNK_CHARS)
        memo = JsonMemo(ctx.files_dir / "chunks")
        done = 0

        async def dehydrate_chunk(number: int, indices: range) -> _Reply:
            nonlocal done
            reply = await memo.get_or_compute(
                {"fingerprint": dict(self.fingerprint()), "lines": self._lines(raw, indices)},
                _Reply,
                lambda: self._ask(ctx, raw, number, len(chunks), indices),
            )
            done += 1
            ctx.report_progress(done, len(chunks))
            return reply

        replies = await asyncio.gather(
            *(dehydrate_chunk(number, indices) for number, indices in enumerate(chunks, start=1))
        )
        dehydrated = Transcript(
            segments=[
                TranscriptSegment(
                    start=raw.segments[paragraph.first].start,
                    end=raw.segments[paragraph.last].end,
                    text=paragraph.text.strip(),
                )
                for reply in replies
                for paragraph in reply.paragraphs
            ]
        )
        self._warn_if_overcut(ctx, raw, dehydrated)
        ctx.write(DEHYDRATED_TRANSCRIPT, dehydrated)

    async def _ask(
        self, ctx: StageContext, raw: Transcript, number: int, total: int, indices: range
    ) -> _Reply:
        messages = [
            ChatMessage("system", self._prompts.render("dehydrate.system.j2")),
            ChatMessage(
                "user",
                self._prompts.render(
                    "dehydrate.user.j2",
                    number=number,
                    total=total,
                    lines=self._lines(raw, indices),
                ),
            ),
        ]
        reply = await complete_json(
            self._chat, messages, _Reply, check=lambda r: _check_references(r, indices)
        )
        ctx.record_usage(reply.usage)
        return reply.value

    @staticmethod
    def _lines(raw: Transcript, indices: range) -> list[tuple[int, str]]:
        return [(index, raw.segments[index].text) for index in indices]

    @staticmethod
    def _warn_if_overcut(ctx: StageContext, raw: Transcript, dehydrated: Transcript) -> None:
        raw_chars = sum(len(segment.text) for segment in raw.segments)
        kept_chars = sum(len(segment.text) for segment in dehydrated.segments)
        if not raw_chars:
            return
        ratio = kept_chars / raw_chars
        low, high = _KEPT_RATIO_RANGE
        if ratio < low:
            ctx.warn(f"脱水后只剩原文的 {ratio:.0%}，可能删掉了有用内容")
        elif ratio > high:
            ctx.warn(f"脱水后仍有原文的 {ratio:.0%}，可能没有充分脱水")


def _check_references(reply: _Reply, indices: range) -> None:
    """每段引用的编号必须在本块之内，且各段按顺序排列、互不重叠。"""
    previous_last = indices.start - 1
    for paragraph in reply.paragraphs:
        if not (previous_last < paragraph.first <= paragraph.last < indices.stop):
            raise InvalidReplyError(
                f"段落编号 [{paragraph.first}, {paragraph.last}] 无效："
                f"必须在 {indices.start}–{indices.stop - 1} 之间、按顺序且互不重叠"
            )
        previous_last = paragraph.last
