from pathlib import Path

import pytest

from dehydrater.pipeline.runner import PipelineDefinitionError, Runner, StageState
from dehydrater.pipeline.stage import Stage, UndeclaredArtifactError
from dehydrater.pipeline.workspace import ArtifactStore, Workspace

from .fakes import DOUBLED, PLUS_ONE, SEED, Double, Number, PlusOne, ReadsUndeclared


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    workspace = Workspace(tmp_path)
    ArtifactStore(workspace).write(SEED, Number(value=3))
    return workspace


def _runner(workspace: Workspace, *stages: Stage) -> Runner:
    return Runner(stages, workspace, sources=[SEED])


async def test_runs_stages_in_order_and_writes_outputs(workspace: Workspace) -> None:
    calls: list[str] = []
    await _runner(workspace, Double(calls), PlusOne(calls)).run()

    assert calls == ["double", "plus_one"]
    assert ArtifactStore(workspace).read(PLUS_ONE) == Number(value=7)


async def test_second_run_hits_cache(workspace: Workspace) -> None:
    calls: list[str] = []
    runner = _runner(workspace, Double(calls), PlusOne(calls))
    await runner.run()
    calls.clear()

    await runner.run()

    assert calls == []
    assert {s.state for s in runner.status()} == {StageState.FRESH}


async def test_changed_input_reruns_only_affected_stages(workspace: Workspace) -> None:
    calls: list[str] = []
    await _runner(workspace, Double(calls), PlusOne(calls)).run()
    calls.clear()

    # double 的参数变了，但结果仍是 6：下游输入摘要不变，所以 plus_one 命中缓存
    ArtifactStore(workspace).write(SEED, Number(value=2))
    await _runner(workspace, Double(calls, factor=3), PlusOne(calls)).run()

    assert calls == ["double"]


async def test_changed_fingerprint_reruns_stage(workspace: Workspace) -> None:
    calls: list[str] = []
    await _runner(workspace, Double(calls)).run()
    calls.clear()

    await _runner(workspace, Double(calls, factor=5)).run()

    assert calls == ["double"]
    assert ArtifactStore(workspace).read(DOUBLED) == Number(value=15)


async def test_deleted_output_invalidates_cache(workspace: Workspace) -> None:
    calls: list[str] = []
    runner = _runner(workspace, Double(calls))
    await runner.run()
    calls.clear()

    (workspace.cache_dir / "artifacts" / "doubled.json").unlink()
    await runner.run()

    assert calls == ["double"]


async def test_force_from_reruns_stage_and_downstream(workspace: Workspace) -> None:
    calls: list[str] = []
    runner = _runner(workspace, Double(calls), PlusOne(calls))
    await runner.run()
    calls.clear()

    await runner.run(force_from="double")

    assert calls == ["double", "plus_one"]


async def test_until_stops_after_stage(workspace: Workspace) -> None:
    calls: list[str] = []
    runner = _runner(workspace, Double(calls), PlusOne(calls))

    await runner.run(until="double")

    assert calls == ["double"]
    assert [s.state for s in runner.status()] == [StageState.FRESH, StageState.PENDING]


def test_rejects_stage_whose_input_is_not_produced_earlier(workspace: Workspace) -> None:
    with pytest.raises(PipelineDefinitionError, match="doubled"):
        _runner(workspace, PlusOne([]), Double([]))


async def test_stage_cannot_read_undeclared_artifact(workspace: Workspace) -> None:
    with pytest.raises(UndeclaredArtifactError):
        await _runner(workspace, ReadsUndeclared()).run()
