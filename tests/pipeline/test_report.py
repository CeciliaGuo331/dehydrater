"""按用户可见的步骤汇总耗时和 token 用量。"""

from datetime import date
from pathlib import Path

from dehydrater.config import Settings
from dehydrater.pipeline.cache import StageMeta
from dehydrater.pipeline.workspace import Workspace
from dehydrater.service import lecture_report


def _write_meta(workspace: Workspace, stage: str, **usage: float) -> None:
    meta = StageMeta(
        cache_key="k",
        output_digests={},
        elapsed_seconds=usage.get("elapsed", 10),
        prompt_tokens=int(usage.get("prompt", 0)),
        completion_tokens=int(usage.get("completion", 0)),
        audio_seconds=usage.get("audio", 0),
    )
    path = workspace.stage_meta_path(stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(meta.model_dump_json())


def test_report_sums_stages_into_steps(tmp_path: Path) -> None:
    recording = tmp_path / "r.mp3"
    recording.write_bytes(b"")
    workspace = Workspace.prepare(
        tmp_path / "out", title="t", lecture_date=date(2026, 9, 30), recording=recording
    )
    _write_meta(workspace, "transcribe", audio=7200)
    _write_meta(workspace, "dehydrate", prompt=1000, completion=100)
    _write_meta(workspace, "outline", prompt=500, completion=50)
    _write_meta(workspace, "write_notes", prompt=300, completion=30)

    report = lecture_report(workspace.root, Settings({}, []))

    steps = {step.step.name: step.usage for step in report.steps}
    assert steps["transcribe"].audio_seconds == 7200
    notes = steps["notes"]  # 大纲 + 撰写
    assert (notes.prompt_tokens, notes.completion_tokens, notes.elapsed_seconds) == (800, 80, 20)
    total = report.total
    assert (total.prompt_tokens, total.completion_tokens, total.elapsed_seconds) == (1800, 180, 40)
