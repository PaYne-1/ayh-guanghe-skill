"""Mixed-batch regressions use the real runner with only provider I/O replaced."""
import json
from pathlib import Path

import pytest

from test_pipeline_runtime_contract import SKILL, approve, package, ready, setup_batch, write


def command(env, capsys, *args, expected=0):
    runner, _, batch, _, _ = env
    assert runner.main([args[0], "--batch", str(batch), *args[1:]]) == expected
    return json.loads(capsys.readouterr().out)


def provider(env, monkeypatch):
    runner, _, _, _, _ = env
    posts = []
    monkeypatch.setenv("AUTODL_API_KEY", "offline")

    def submit(item, key, dry_run):
        digest = runner._load_autodl().submit_payload(item / "_工作文件/任务状态/提交请求.json", dry_run=True)["request_hash"]
        if dry_run:
            return {"request_hash": digest, "dry_run": True}
        posts.append(runner._attempt_key(item))
        return {"request_hash": digest, "task_id": f"task-{len(posts)}", "response": {"code": 0}}

    def download(url, item):
        path = item / "_工作文件/生成过程/视频候选.mp4"
        path.write_bytes(runner._attempt_key(item).encode())
        return path

    monkeypatch.setattr(runner, "_submit_item", submit)
    monkeypatch.setattr(runner, "_poll_item", lambda *a, **k: {"status": "completed", "url": "offline://candidate"})
    monkeypatch.setattr(runner, "_download_item", download)
    monkeypatch.setattr(runner, "validate_video_file", lambda path, resolution: {
        "ok": True, "full_decode": True, "sha256": runner._sha256(path), "candidate": str(path.resolve()), "has_audio": True,
    })
    return posts


def review(env, capsys, decisions):
    runner, _, batch, items, _ = env
    workflow = runner._load_workflow_cli()
    result = batch / "review-input.json"
    write(result, {"items": [{"video_id": video_id, "decision": decision, "reason": "bad dialogue" if decision == "failed" else "", "artifacts": {"视频.mp4": workflow._review_media(batch, next(i for i in items if i.name.startswith(video_id)), "视频.mp4")}} for video_id, decision in decisions.items()]})
    return command(env, capsys, "complete-review", "--result", str(result), "--knowledge-dir", str(batch / "knowledge"))


def test_passed_sibling_survives_second_review_after_v02(setup_batch, capsys, monkeypatch):
    env = setup_batch
    runner, policy, batch, items, _ = env
    ready(env, capsys)
    posts = provider(env, monkeypatch)
    assert command(env, capsys, "run-local")["kind"] == "USER_FINAL_REVIEW_REQUIRED"
    assert review(env, capsys, {"V001": "passed", "V002": "failed"})["video_ids"] == ["V002"]
    evidence_path = items[0] / "_工作文件/验收记录/视频技术检查.json"
    evidence_before = evidence_path.read_bytes()
    promoted = runner._load_workflow_cli().validated_promoted_artifact_path(items[0], "视频.mp4")
    promoted_hash = runner._sha256(promoted)
    command(env, capsys, "approve-rerun", "--video-id", "V002", "--approved-cost", "3")
    assert command(env, capsys, "run-local")["kind"] == "USER_FINAL_REVIEW_REQUIRED"
    assert review(env, capsys, {"V001": "passed", "V002": "passed"})["kind"] == "DONE"
    assert posts == ["V001:V01", "V002:V01", "V002:V02"]
    assert evidence_path.read_bytes() == evidence_before
    assert runner._sha256(promoted) == promoted_hash
    assert all(runner._task_info(item)["status"] == "COMPLETED" for item in items)
    assert runner.load_or_create_state(batch, policy).status == "COMPLETED"


def test_diagnostic_receipt_cannot_replace_multi_video_human_gate(setup_batch, capsys, monkeypatch):
    env = setup_batch
    runner, policy, batch, _, _ = env
    ready(env, capsys)
    provider(env, monkeypatch)
    command(env, capsys, "run-local")
    review(env, capsys, {"V001": "failed", "V002": "failed"})
    diagnostic = command(env, capsys, "reserve-diagnostic", "--video-id", "V001", "--reason", "offline diagnosis")
    state = runner.load_or_create_state(batch, policy)
    assert state.human_gate["video_ids"] == ["V001", "V002"]
    assert command(env, capsys, "next") == diagnostic
    write(Path(diagnostic["output_path"]), {"summary": "repair locally"})
    command(env, capsys, "accept-diagnostic", "--action-id", diagnostic["action_id"], "--result", diagnostic["output_path"])
    assert command(env, capsys, "next")["video_ids"] == ["V001", "V002"]
    command(env, capsys, "approve-rerun", "--video-id", "V001", "--approved-cost", "3")
    assert runner.load_or_create_state(batch, policy).human_gate["video_ids"] == ["V002"]
    assert command(env, capsys, "run-local")["video_ids"] == ["V002"]


@pytest.mark.parametrize("stage", ["preflight", "payload", "network", "download", "decode"])
def test_repaired_environment_resumes_same_attempt_without_terminal_block(setup_batch, capsys, monkeypatch, stage):
    env = setup_batch
    runner, policy, batch, items, _ = env
    ready(env, capsys)
    posts = provider(env, monkeypatch)
    attribute = {"payload": "prepare_payload", "network": "_poll_item", "download": "_download_item", "decode": "validate_video_file"}.get(stage)
    original = getattr(runner, attribute) if attribute else None
    if stage == "preflight":
        monkeypatch.delenv("AUTODL_API_KEY")
    else:
        def broken(*a, **k):
            raise OSError("repairable offline environment failure")
        monkeypatch.setattr(runner, attribute, broken)
    command(env, capsys, "run-local")
    action = command(env, capsys, "next")
    assert action["kind"] == "LOCAL_WORK_REQUIRED"
    assert runner.load_or_create_state(batch, policy).status != "BLOCKED"
    assert all(runner._item_retry_count(item) == 0 for item in items)
    if attribute:
        monkeypatch.setattr(runner, attribute, original)
    else:
        monkeypatch.setenv("AUTODL_API_KEY", "offline")
    assert command(env, capsys, "run-local")["kind"] == "USER_FINAL_REVIEW_REQUIRED"
    assert posts == ["V001:V01", "V002:V01"]


def test_prepost_sibling_is_not_reviewed_or_rerunnable_and_can_finish_v01(setup_batch, capsys, monkeypatch):
    env = setup_batch
    runner, policy, batch, items, _ = env
    ready(env, capsys)
    posts = provider(env, monkeypatch)
    original = runner._submit_item

    def preflight(item, key, dry_run):
        if item == items[1] and dry_run:
            raise ValueError("repair local payload dependency")
        return original(item, key, dry_run)

    monkeypatch.setattr(runner, "_submit_item", preflight)
    result = command(env, capsys, "run-local")
    assert result["kind"] == "USER_FINAL_REVIEW_REQUIRED"
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert 'data-video-id="V001"' in report
    assert 'data-video-id="V002"' not in report
    assert not runner._task_info(items[1]).get("task_id")
    result = review(env, capsys, {"V001": "passed"})
    assert result["kind"] == "LOCAL_WORK_REQUIRED"
    assert runner._load_workflow_cli().validated_promoted_artifact_path(items[0], "视频.mp4") is not None
    assert runner.load_or_create_state(batch, policy).status == "RUNNING_AUTOMATICALLY"
    command(env, capsys, "approve-rerun", "--video-id", "V002", "--approved-cost", "3", expected=2)
    assert runner._item_retry_count(items[1]) == 0
    state = runner.load_or_create_state(batch, policy)
    assert runner._route_video_failures(batch, state, {"V002": "no actual paid attempt"})["kind"] != "USER_RERUN_APPROVAL_REQUIRED"
    monkeypatch.setattr(runner, "_submit_item", original)
    assert command(env, capsys, "run-local")["kind"] == "USER_FINAL_REVIEW_REQUIRED"
    assert review(env, capsys, {"V001": "passed", "V002": "passed"})["kind"] == "DONE"
    assert posts == ["V001:V01", "V002:V01"]


@pytest.mark.parametrize("malformed", [[], "wrong", None, {"storyboard_people": None}, {"hashtags": None}, {"people": [None, "bad"]}, {"script_segments": [{"dialogue": []}]}])
def test_malformed_content_shapes_are_bounded_correction_failures(setup_batch, capsys, malformed):
    env = setup_batch
    runner, policy, batch, items, _ = env
    action = approve(env, capsys)
    for attempt in range(2):
        for item in items:
            value = {**package(item.name[:4]), **malformed} if isinstance(malformed, dict) else malformed
            write(Path(action["output_dir"]) / f"{item.name[:4]}.json", value)
        result = command(env, capsys, "accept-content", "--content-dir", action["output_dir"], "--profile", str(SKILL / "profiles/爱优护电动轮椅_淘宝天猫光合.json"), "--action-id", action["action_id"])
        assert result["ok"] is False
        assert set(result["failures"]) == {"V001", "V002"}
        action = command(env, capsys, "next")
        if attempt == 0:
            assert action["purpose"] == "content_correction"
    assert action["kind"] == "BLOCKED"
    state = runner.load_or_create_state(batch, policy)
    assert state.model_usage == {"content_create": 1, "content_correction": 1}
    assert not state.image_calls_by_video


@pytest.mark.parametrize("changed_field,changed_value", [("sha256", "0" * 64), ("version", "V02")])
def test_failed_feedback_requires_current_report_hash_and_version(setup_batch, capsys, monkeypatch, changed_field, changed_value):
    env = setup_batch
    runner, policy, batch, items, _ = env
    ready(env, capsys)
    posts = provider(env, monkeypatch)
    command(env, capsys, "run-local")
    workflow = runner._load_workflow_cli()
    decisions = [{"video_id": item.name[:4], "decision": "failed", "reason": "reviewed old candidate", "artifacts": {"视频.mp4": workflow._review_media(batch, item, "视频.mp4")}} for item in items]
    decisions[0]["artifacts"]["视频.mp4"][changed_field] = changed_value
    path = batch / "stale-review.json"
    write(path, {"items": decisions})
    command(env, capsys, "complete-review", "--result", str(path), "--knowledge-dir", str(batch / "knowledge"), expected=2)
    assert runner.load_or_create_state(batch, policy).status == "WAITING_FINAL_REVIEW"
    assert posts == ["V001:V01", "V002:V01"]
    assert not (batch / "批次验收结果.json").exists()


def test_default_review_renderer_does_not_create_blank_candidate_cards(setup_batch):
    runner, _, batch, items, _ = setup_batch
    report = runner._load_workflow_cli().build_review_report(batch)
    assert 'class="video-card"' not in report.read_text(encoding="utf-8")


def test_fabricated_human_gate_does_not_authorize_unsubmitted_v02(setup_batch, capsys):
    runner, policy, batch, items, _ = setup_batch
    state = ready(setup_batch, capsys)
    state.status = "WAITING_RERUN_APPROVAL"
    state.human_gate = {"kind": "USER_RERUN_APPROVAL_REQUIRED", "video_ids": ["V001"]}
    runner.save_state(batch, state)
    result = command(setup_batch, capsys, "approve-rerun", "--video-id", "V001", "--approved-cost", "3", expected=2)
    assert "真实 V01" in result["reason"]
    assert runner._item_retry_count(items[0]) == 0
    assert (items[0] / "_工作文件/任务状态/提交请求.json").is_file()


@pytest.mark.parametrize("damage", ["missing", "tamper", "demote"])
def test_final_completion_reaudits_previously_completed_sibling(setup_batch, capsys, monkeypatch, damage):
    env = setup_batch
    runner, policy, batch, items, _ = env
    ready(env, capsys)
    posts = provider(env, monkeypatch)
    original = runner._submit_item

    def preflight(item, key, dry_run):
        if item == items[1] and dry_run:
            raise ValueError("repair before V002 first POST")
        return original(item, key, dry_run)

    monkeypatch.setattr(runner, "_submit_item", preflight)
    command(env, capsys, "run-local")
    assert review(env, capsys, {"V001": "passed"})["kind"] == "LOCAL_WORK_REQUIRED"
    assert runner._task_info(items[0])["status"] == "COMPLETED"
    workflow = runner._load_workflow_cli()
    final = workflow.validated_promoted_artifact_path(items[0], "视频.mp4")
    original_bytes = final.read_bytes()
    candidate = items[0] / "_工作文件/生成过程/视频候选.mp4"
    candidate.unlink()
    if damage == "missing":
        final.unlink()
    elif damage == "tamper":
        final.write_bytes(b"corrupted-after-prior-completion")
    else:
        workflow.record_artifact_decision(items[0], "视频.mp4", final, "failed", "offline-test", "revoked prior approval")
    monkeypatch.setattr(runner, "_submit_item", original)
    command(env, capsys, "run-local")
    result = review(env, capsys, {"V002": "passed"})
    assert result["kind"] == "LOCAL_OUTPUT_REPAIR_REQUIRED"
    assert result["video_ids"] == ["V001"]
    assert result["paid_generation_allowed"] is False
    assert "视频.mp4" in json.dumps(result["items"], ensure_ascii=False)
    audit = json.loads(Path(result["audit_path"]).read_text(encoding="utf-8"))
    audit_bytes = Path(result["audit_path"]).read_bytes()
    assert len(audit["items"]) == 2
    assert len(audit["items"][0]["valid"]) == 6
    assert len(audit["items"][1]["valid"]) == 7
    if damage != "missing":
        assert audit["items"][0]["demoted"]
    state = runner.load_or_create_state(batch, policy)
    assert state.status == "RUNNING_AUTOMATICALLY"
    assert state.item_failures["V001"]["kind"] == "output_repair"
    assert runner._task_info(items[0])["status"] == "OUTPUT_REPAIR_REQUIRED"
    assert runner._task_info(items[1])["status"] == "COMPLETED"
    assert command(env, capsys, "next")["kind"] == "LOCAL_OUTPUT_REPAIR_REQUIRED"
    assert command(env, capsys, "run-local")["kind"] == "LOCAL_OUTPUT_REPAIR_REQUIRED"
    assert Path(result["audit_path"]).read_bytes() == audit_bytes
    command(env, capsys, "approve-rerun", "--video-id", "V001", "--approved-cost", "3", expected=2)
    assert posts == ["V001:V01", "V002:V01"]
    # Repair only from known approved bytes; no provider call or new generation.
    candidate.write_bytes(original_bytes)
    if damage == "demote":
        event = workflow.record_artifact_decision(items[0], "视频.mp4", candidate, "passed", "offline-test", "explicitly reinstated exact prior bytes")
    else:
        event = workflow.latest_artifact_decision(workflow.load_approval_events(items[0]), "视频.mp4", runner._sha256(candidate))
    workflow.promote_approved_artifact(items[0], event)
    assert command(env, capsys, "run-local")["kind"] == "DONE"
    assert posts == ["V001:V01", "V002:V01"]
    assert runner.load_or_create_state(batch, policy).item_failures == {}
    assert all(runner._task_info(item)["status"] == "COMPLETED" for item in items)


def test_done_response_rechecks_outputs_instead_of_trusting_completed_status(setup_batch, capsys, monkeypatch):
    runner, policy, batch, items, _ = setup_batch
    ready(setup_batch, capsys)
    posts = provider(setup_batch, monkeypatch)
    command(setup_batch, capsys, "run-local")
    assert review(setup_batch, capsys, {"V001": "passed", "V002": "passed"})["kind"] == "DONE"
    (items[0] / "封面图.png").unlink()
    result = command(setup_batch, capsys, "next")
    assert result["kind"] == "LOCAL_OUTPUT_REPAIR_REQUIRED"
    assert "封面图.png" in result["items"]["V001"]["missing"]
    assert runner.load_or_create_state(batch, policy).status != "COMPLETED"
    assert posts == ["V001:V01", "V002:V01"]
