"""导读：通读脱水逐字稿，生成概览、分节提要、术语表和课堂通知。

与脱水阶段一样，模型只引用段落编号，时间由编号换算，不让模型编造时间。
"""

from pydantic import BaseModel

from dehydrater.domain.guide import Guide, GuideNotice, GuideSection, GuideTerm
from dehydrater.domain.transcript import Transcript
from dehydrater.pipeline.artifacts import DEHYDRATED_TRANSCRIPT, GUIDE, LECTURE
from dehydrater.pipeline.stage import Stage, StageContext
from dehydrater.pipeline.structured import InvalidReplyError, complete_json
from dehydrater.pipeline.templating import TemplateSet
from dehydrater.ports import ChatMessage, ChatModel, Fingerprint

_PROMPTS = ("guide.system.j2", "guide.user.j2")


class _Section(BaseModel):
    title: str
    paragraph: int
    summary: str
    key_points: list[str]


class _Term(BaseModel):
    term: str
    explanation: str


class _Notice(BaseModel):
    text: str
    paragraph: int


class _Reply(BaseModel):
    overview: str
    sections: list[_Section]
    key_terms: list[_Term]
    notices: list[_Notice]


class WriteGuideStage(Stage):
    name = "write_guide"
    inputs = (LECTURE, DEHYDRATED_TRANSCRIPT)
    outputs = (GUIDE,)

    def __init__(self, chat: ChatModel, prompts: TemplateSet) -> None:
        self._chat = chat
        self._prompts = prompts

    def fingerprint(self) -> Fingerprint:
        return {**self._chat.fingerprint(), "prompts": self._prompts.digest(*_PROMPTS)}

    async def run(self, ctx: StageContext) -> None:
        lecture = ctx.read(LECTURE)
        transcript = ctx.read(DEHYDRATED_TRANSCRIPT)
        messages = [
            ChatMessage("system", self._prompts.render("guide.system.j2")),
            ChatMessage(
                "user",
                self._prompts.render(
                    "guide.user.j2", lecture=lecture, paragraphs=transcript.segments
                ),
            ),
        ]
        reply = await complete_json(
            self._chat, messages, _Reply, check=lambda r: _check_references(r, transcript)
        )
        ctx.record_usage(reply.usage)
        ctx.write(GUIDE, _to_guide(reply.value, transcript))


def _check_references(reply: _Reply, transcript: Transcript) -> None:
    count = len(transcript.segments)
    referenced = [s.paragraph for s in reply.sections] + [n.paragraph for n in reply.notices]
    if invalid := [index for index in referenced if not 0 <= index < count]:
        raise InvalidReplyError(f"段落编号 {invalid} 不存在，有效范围是 0–{count - 1}")
    starts = [section.paragraph for section in reply.sections]
    if starts != sorted(starts):
        raise InvalidReplyError("sections 必须按 paragraph 从小到大排列")


def _to_guide(reply: _Reply, transcript: Transcript) -> Guide:
    def at(paragraph: int) -> float:
        return transcript.segments[paragraph].start

    return Guide(
        overview=reply.overview,
        sections=[
            GuideSection(
                title=section.title,
                start=at(section.paragraph),
                summary=section.summary,
                key_points=section.key_points,
            )
            for section in reply.sections
        ],
        key_terms=[GuideTerm(term=t.term, explanation=t.explanation) for t in reply.key_terms],
        notices=[
            GuideNotice(text=notice.text, at=at(notice.paragraph)) for notice in reply.notices
        ],
    )
