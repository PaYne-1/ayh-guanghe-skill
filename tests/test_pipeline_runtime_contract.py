"""Offline integration regressions for the externally driven runner contract."""
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skill-package" / "product-video-pipeline"


def module(name="pipeline_runner"):
    spec = importlib.util.spec_from_file_location(name, SKILL / "scripts" / f"{name}.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def record_offline_submission(runner, item, task_id="offline-task"):
    info = runner._task_info(item)
    info.update({"video_id": item.name[:4], "task_id": task_id, "request_hash": "offline-request-" + task_id, "submission_pending": False})
    runner._write_task_info(item, info)


def package(video_id):
    return {
        "video_id": video_id, "selling_point": "操作简单",
        "publish_title": "爸妈也能轻松上手的电动轮椅到底怎么样", "cover_title": "爸妈会操作",
        "people": [{"id": "P1", "identity": "老人", "gender": "女", "age_feel": "70岁", "position": "左侧", "action": "坐轮椅", "speaks": True}, {"id": "P2", "identity": "家属", "gender": "女", "age_feel": "40岁", "position": "右侧", "action": "提问", "speaks": True}],
        "storyboard_people": ["P1", "P2"],
        "script_segments": [{"start": 0, "end": 4, "speaker_id": "P2", "dialogue": "这个操作会不会很难？"}, {"start": 4, "end": 11, "speaker_id": "P1", "dialogue": "操作很顺手，我自己就能开，家里人也省心。"}, {"start": 11, "end": 15, "speaker_id": "P2", "dialogue": "用了爱优护电动轮椅后，出门更方便，可以了解一下。"}],
        "storyboard_prompt": "竖屏9:16，两位女性始终同框，不要文字。", "last_frame_prompt": "合理尾帧，主体前进1至1.5米，人物产品一致。",
        "video_prompt": "一镜到底，连续平稳运镜，完整双人对话口播，不要背景音乐。",
        "publish_body": "以前老人总担心操作复杂，家里人每次都要陪在旁边。用了爱优护电动轮椅后，老人自己很快就能上手，平时在小区出门顺手多了，家属照顾也省心。有同样出门需求的家庭，可以了解一下爱优护电动轮椅。",
        "hashtags": ["#爱优护电动轮椅", "#ainsnbot高端智能电动轮椅", "#电动轮椅", "#老人专用电动轮椅"],
    }


@pytest.fixture
def setup_batch(tmp_path):
    runner = module()
    policy = module("pipeline_policy").load_policy(SKILL)
    batch = tmp_path / "batch"
    items = [batch / f"V{i:03d}_操作简单_待生成" for i in range(1, 3)]
    for item in items:
        write(item / "_工作文件/任务状态/任务信息.json", {"video_id": item.name[:4], "retry_count": 0, "status": "CREATED"})
    product = tmp_path / "product.png"
    cover = tmp_path / "style" / "reference.png"
    cover.parent.mkdir()
    Image.new("RGB", (90, 160), "red").save(product)
    Image.new("RGB", (90, 160), "blue").save(cover)
    write(batch / "启动确认单.json", {"product_images": [str(product)], "cover_reference_dir": str(cover.parent), "product_name": "爱优护电动轮椅", "total_videos": 2, "resolution": "768P", "duration_seconds": 15, "max_budget_yuan": "10.00", "unit_price_yuan": "3.00", "live_price": {"queried_at": "2026-09-08"}, "image_provider": "gpt_web", "image_api_config": {}})
    state = runner.load_or_create_state(batch, policy)
    return runner, policy, batch, items, state


def approve(env, capsys):
    runner, policy, batch, items, _ = env
    assert runner.main(["approve-start", "--batch", str(batch), "--approved-budget", "10", "--estimated-v01-total", "6", "--image-provider", "gpt_web"]) == 0
    action = json.loads(capsys.readouterr().out)
    return action


def accept_content(env, action, capsys):
    runner, policy, batch, items, _ = env
    output = Path(action["output_dir"])
    for item in items:
        write(output / f"{item.name[:4]}.json", package(item.name[:4]))
    assert runner.main(["accept-content", "--batch", str(batch), "--content-dir", str(output), "--profile", str(SKILL / "profiles/爱优护电动轮椅_淘宝天猫光合.json"), "--action-id", action["action_id"]]) == 0
    return json.loads(capsys.readouterr().out)


def next_image(env, capsys, color="green"):
    runner, policy, batch, items, _ = env
    assert runner.main(["next", "--batch", str(batch)]) == 0
    action = json.loads(capsys.readouterr().out)
    assert action["kind"] == "GPT_WEB_IMAGE_REQUIRED"
    output = Path(action["output_path"])
    Image.new("RGB", (2160, 3840), color).save(output)
    assert runner.main(["accept-image", "--batch", str(batch), "--video-id", action["video_id"], "--artifact", action["artifact"], "--source", str(output), "--action-id", action["action_id"]]) == 0
    capsys.readouterr()
    return action


def test_actions_drive_real_prompts_payload_and_review_report(setup_batch, capsys, monkeypatch):
    env = setup_batch
    runner, policy, batch, items, state = env
    action = approve(env, capsys)
    assert action["kind"] == "BATCH_CONTENT_REQUIRED"
    assert action.get("action_id"), "model action must be reserved before external work"
    accept_content(env, action, capsys)
    for index in range(6):
        image_action = next_image(env, capsys, (index * 30, 50, 100))
        assert image_action["reference_paths"]
        if image_action["artifact"] == "尾帧图.png":
            assert any(path.endswith("分镜图.png") for path in image_action["reference_paths"])
    assert runner.main(["next", "--batch", str(batch)]) == 0
    action = json.loads(capsys.readouterr().out)
    assert action["kind"] == "LOCAL_WORK_REQUIRED"
    for item in items:
        payload = json.loads((item / "_工作文件/任务状态/提交请求.json").read_text(encoding="utf-8"))
        assert payload["first_frame"].startswith("data:image/png;base64,")
        assert "P1" in payload["prompt"] and "P2" in payload["prompt"]
    def execute(batch, item, state, **kwargs):
        record_offline_submission(runner, item, item.name[:4])
        candidate = item / "_工作文件/生成过程/视频候选.mp4"
        candidate.write_bytes(b"offline-video")
        evidence = {"ok": True, "full_decode": True, "sha256": runner._sha256(candidate), "candidate": str(candidate.resolve()), "version": "V01"}
        return {"ok": True, "candidate": str(candidate), "technical": evidence, "task_id": item.name[:4]}
    monkeypatch.setattr(runner, "run_autodl_item", execute)
    assert runner.main(["run-local", "--batch", str(batch)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["kind"] == "USER_FINAL_REVIEW_REQUIRED"
    assert Path(result["report_path"]).is_file()


def test_final_video_prompt_preflight_persists_closed_dialogue_contract(setup_batch, capsys):
    """The paid payload is the compiled contract, never raw model prose."""
    runner, policy, batch, items, _ = setup_batch
    action = approve(setup_batch, capsys)
    accept_content(setup_batch, action, capsys)
    for index in range(6):
        next_image(setup_batch, capsys, (index * 20, 70, 120))

    assert runner.main(["next", "--batch", str(batch)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["kind"] == "LOCAL_WORK_REQUIRED"
    payload_path = items[0] / "_工作文件/任务状态/提交请求.json"
    prompt_path = items[0] / "_工作文件/生成过程/视频提交提示词.txt"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    prompt = payload["prompt"]
    assert prompt_path.read_text(encoding="utf-8") == prompt
    for required in (
        "产品参考图是唯一产品依据",
        "0–15秒全程一个连续镜头",
        "固定中远景",
        "人物全身和产品整体始终完整位于画面安全区",
        "非当前说话者嘴巴闭合且完全不发声",
        "清单之外零人声",
        "不得添加任何额外语音",
        "不得添加背景音乐",
    ):
        assert required in prompt
    content = package("V001")
    for segment in content["script_segments"]:
        binding = f"{segment['start']}–{segment['end']}秒 speaker_id={segment['speaker_id']}（"
        assert prompt.count(segment["dialogue"]) == 1
        assert binding in prompt
    state = runner.load_or_create_state(batch, policy)
    assert state.budget_ledger == {}
    assert state.image_budget_ledger == {}


def test_prepare_payload_preserves_existing_prompt_when_new_payload_mismatches(
    setup_batch, capsys
):
    runner, policy, batch, items, _ = setup_batch
    action = approve(setup_batch, capsys)
    accept_content(setup_batch, action, capsys)
    for index in range(3):
        next_image(setup_batch, capsys, (index * 20, 70, 120))
    state = runner.load_or_create_state(batch, policy)
    payload_path = runner.prepare_payload(batch, items[0], state)
    prompt_path = items[0] / "_工作文件/生成过程/视频提交提示词.txt"
    original_payload = payload_path.read_text(encoding="utf-8")
    original_prompt = prompt_path.read_text(encoding="utf-8")
    content_path = items[0] / "_工作文件/生成过程/策划内容.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    content["video_prompt"] += "\n家属自然同行，保持画面稳定。"
    write(content_path, content)

    with pytest.raises(PermissionError, match="已准备提交请求"):
        runner.prepare_payload(batch, items[0], state)

    assert payload_path.read_text(encoding="utf-8") == original_payload
    assert prompt_path.read_text(encoding="utf-8") == original_prompt
    assert json.loads(original_payload)["prompt"] == original_prompt


def test_v01_archive_moves_submission_prompt_with_submission_request(tmp_path):
    runner = module()
    item = tmp_path / "V001_操作简单_待生成"
    request = item / "_工作文件/任务状态/提交请求.json"
    prompt = item / "_工作文件/生成过程/视频提交提示词.txt"
    write(request, {"prompt": "V01 提交提示词"})
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("V01 提交提示词", encoding="utf-8")

    runner._archive_v01_for_rerun(item)

    archive = item / "_工作文件/历史版本/视频版本/V01_初次生成"
    assert not request.exists()
    assert not prompt.exists()
    assert (archive / "提交请求.json").is_file()
    assert (archive / "视频提交提示词.txt").read_text(encoding="utf-8") == "V01 提交提示词"


def test_v01_archive_rejects_unpaired_archive_conflict_without_moving_sources(tmp_path):
    runner = module()
    item = tmp_path / "V001_操作简单_待生成"
    request = item / "_工作文件/任务状态/提交请求.json"
    prompt = item / "_工作文件/生成过程/视频提交提示词.txt"
    write(request, {"prompt": "V01 提交提示词"})
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("V01 提交提示词", encoding="utf-8")
    archive = item / "_工作文件/历史版本/视频版本/V01_初次生成"
    write(archive / "提交请求.json", {"prompt": "冲突版本"})

    with pytest.raises(ValueError, match="成对"):
        runner._archive_v01_for_rerun(item)

    assert request.is_file()
    assert prompt.is_file()
    assert not (archive / "视频提交提示词.txt").exists()


def test_v01_archive_rolls_back_pair_when_staged_copy_fails(tmp_path, monkeypatch):
    runner = module()
    item = tmp_path / "V001_操作简单_待生成"
    request = item / "_工作文件/任务状态/提交请求.json"
    prompt = item / "_工作文件/生成过程/视频提交提示词.txt"
    write(request, {"prompt": "V01 提交提示词"})
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("V01 提交提示词", encoding="utf-8")
    real_copy = runner.shutil.copy2

    def fail_prompt_copy(source, target, *args, **kwargs):
        if Path(source) == prompt:
            Path(target).write_bytes(b"partial copy")
            raise OSError("simulated prompt copy failure")
        return real_copy(source, target, *args, **kwargs)

    monkeypatch.setattr(runner.shutil, "copy2", fail_prompt_copy)
    with pytest.raises(OSError, match="simulated"):
        runner._archive_v01_for_rerun(item)

    archive = item / "_工作文件/历史版本/视频版本/V01_初次生成"
    assert request.is_file()
    assert prompt.is_file()
    assert not (archive / "提交请求.json").exists()
    assert not (archive / "视频提交提示词.txt").exists()
    assert not list(archive.glob("*.tmp"))


@pytest.mark.parametrize("field", ["storyboard_prompt", "last_frame_prompt", "video_prompt"])
def test_content_validation_rejects_product_appearance_description(field):
    workflow = module("workflow_cli")
    profile = json.loads(
        (SKILL / "profiles" / "爱优护电动轮椅_淘宝天猫光合.json").read_text(encoding="utf-8")
    )
    content = package("V001")
    content[field] = "红色车架在阳光下清晰可见。"

    assert "product.appearance_description_forbidden" in workflow.validate_content_package(
        content, profile
    )


@pytest.mark.parametrize(
    "field, prose",
    [
        ("storyboard_prompt", "老人手放控制器上，保持扶手结构一致。"),
        ("last_frame_prompt", "不要改变靠背，产品整体自然前进。"),
        ("video_prompt", "一镜到底，连续平稳运镜，完整双人对话口播，手放控制器上，不要背景音乐。"),
        ("storyboard_prompt", "老人穿红色衣服，手放控制器。"),
        ("video_prompt", "一镜到底，连续平稳运镜，完整双人对话口播，按控制器增加速度，不要背景音乐。"),
    ],
)
def test_content_validation_allows_component_action_and_reference_lock(field, prose):
    workflow = module("workflow_cli")
    profile = json.loads(
        (SKILL / "profiles" / "爱优护电动轮椅_淘宝天猫光合.json").read_text(encoding="utf-8")
    )
    content = package("V001")
    content[field] = prose

    assert "product.appearance_description_forbidden" not in workflow.validate_content_package(
        content, profile
    )


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (
            lambda content: content["script_segments"].__setitem__(
                1, dict(content["script_segments"][1], dialogue=content["script_segments"][0]["dialogue"])
            ),
            "视频台词不得重复",
        ),
        (
            lambda content: content.__setitem__("video_prompt", "一镜到底，允许额外人声作为环境口播。"),
            "video.extra_voice_permission_forbidden",
        ),
        (
            lambda content: content.__setitem__("video_prompt", "红色车架在阳光下清晰可见。"),
            "产品外观",
        ),
    ],
)
def test_final_video_prompt_preflight_blocks_invalid_source_before_paid_reservation(
    setup_batch, capsys, mutate, expected
):
    runner, policy, batch, items, _ = setup_batch
    action = approve(setup_batch, capsys)
    accept_content(setup_batch, action, capsys)
    for index in range(3):
        next_image(setup_batch, capsys, (index * 30, 60, 110))
    content_path = items[0] / "_工作文件/生成过程/策划内容.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    mutate(content)
    write(content_path, content)
    state = runner.load_or_create_state(batch, policy)

    with pytest.raises(ValueError, match=expected):
        runner.prepare_payload(batch, items[0], state)

    assert state.budget_ledger == {}
    assert state.image_budget_ledger == {}


def test_next_reservation_is_durable_idempotent_and_budgeted(setup_batch, capsys):
    runner, policy, batch, items, _ = setup_batch
    first = approve(setup_batch, capsys)
    state = runner.load_or_create_state(batch, policy)
    assert state.model_calls_batch == 1
    assert runner.next_action(batch, state, policy) == first
    assert state.model_calls_batch == 1
    state.pending_action = None
    state.model_actions[first["action_id"]]["status"] = "failed"
    state.model_usage["content_correction"] = 1
    state.item_failures["V001"] = {"kind": "content", "reason": "bad"}
    state.item_failures["V002"] = {"kind": "content", "reason": "bad"}
    runner.save_state(batch, state)
    action = runner.next_action(batch, state, policy)
    assert action["kind"] == "BLOCKED"


def test_approved_manifest_rejects_added_item_and_changed_resolution(setup_batch, capsys):
    runner, policy, batch, items, _ = setup_batch
    approve(setup_batch, capsys)
    state = runner.load_or_create_state(batch, policy)
    assert state.approved_manifest["item_count"] == 2
    (batch / "V003_extra").mkdir()
    with pytest.raises(PermissionError, match="清单|项目"):
        runner.validate_approved_manifest(batch, state)
    (batch / "V003_extra").rmdir()
    confirmation = json.loads((batch / "启动确认单.json").read_text(encoding="utf-8"))
    confirmation["resolution"] = "2K"
    write(batch / "启动确认单.json", confirmation)
    with pytest.raises(PermissionError, match="清单|配置"):
        runner.validate_approved_manifest(batch, state)


def test_dry_run_preserves_production_state(setup_batch, capsys, monkeypatch):
    runner, policy, batch, items, state = setup_batch
    approve(setup_batch, capsys)
    state = runner.load_or_create_state(batch, policy)
    before = copy.deepcopy(runner.asdict(state))
    bytes_before = (batch / runner.STATE_FILENAME).read_bytes()
    monkeypatch.setattr(runner, "run_autodl_item", lambda *a, **k: {"ok": True, "dry_run": True})
    result = runner.run_local_until_gate(batch, state, policy, dry_run=True)
    assert result["kind"] == "DRY_RUN_COMPLETE"
    assert runner.asdict(state) == before
    assert (batch / runner.STATE_FILENAME).read_bytes() == bytes_before


def test_image_failure_is_local_and_commands_require_running_state(setup_batch, capsys):
    runner, policy, batch, items, state = setup_batch
    source = batch / "bad.png"
    source.write_bytes(b"broken")
    assert runner.main(["accept-image", "--batch", str(batch), "--video-id", "V001", "--artifact", "分镜图.png", "--source", str(source)]) == 2
    assert "状态" in json.loads(capsys.readouterr().out)["reason"]
    assert runner.load_or_create_state(batch, policy).model_calls_by_video == {}
    state.status = "RUNNING_AUTOMATICALLY"
    runner.record_image_failure(state, video_id="V001", artifact="分镜图.png", reason="broken")
    runner.record_image_failure(state, video_id="V001", artifact="分镜图.png", reason="broken")
    assert state.status == "RUNNING_AUTOMATICALLY"
    assert "V001" in state.item_failures


def test_video_validation_requires_full_decode(tmp_path, monkeypatch):
    runner = module()
    candidate = tmp_path / "candidate.mp4"
    candidate.write_bytes(b"corrupt-packets-with-readable-metadata")
    calls = []
    def probe(args, **kwargs):
        calls.append(args)
        if args[0] == "ffprobe":
            return subprocess.CompletedProcess(args, 0, json.dumps({"streams": [{"codec_type": "video", "width": 768, "height": 1365}, {"codec_type": "audio"}], "format": {"duration": "15"}}), "")
        return subprocess.CompletedProcess(args, 1, "", "Invalid data")
    monkeypatch.setattr(runner.subprocess, "run", probe)
    with pytest.raises(ValueError, match="全片|解码"):
        runner.validate_video_file(candidate, "768P")
    assert any(args[0] == "ffmpeg" for args in calls)


def test_auth_preflight_and_raw_scheme(setup_batch, monkeypatch):
    runner, policy, batch, items, state = setup_batch
    monkeypatch.delenv("AUTODL_API_KEY", raising=False)
    state.status = "RUNNING_AUTOMATICALLY"
    monkeypatch.setattr(runner, "_submit_item", lambda *a, **k: {"request_hash": "h"})
    with pytest.raises((ValueError, PermissionError), match="AUTODL_API_KEY"):
        runner.run_autodl_item(batch, items[0], state)
    assert not runner._task_info(items[0]).get("submission_pending")
    monkeypatch.setenv("AUTODL_AUTH_SCHEME", "raw")
    fake = module("autodl_h3")
    seen = []
    monkeypatch.setattr(fake, "poll_task", lambda *a, **k: seen.append(k) or {"status": "poll_timeout"})
    monkeypatch.setattr(runner, "_load_autodl", lambda: fake)
    runner._poll_item("task", "secret")
    assert seen[0]["auth_scheme"] == "raw"


@pytest.mark.parametrize("field,value", [("status", "BOGUS"), ("status", []), ("schema_version", 99), ("model_calls_batch", -1), ("completed_nodes", [])])
def test_persisted_state_is_validated(setup_batch, field, value):
    runner, policy, batch, items, state = setup_batch
    raw = runner.asdict(state)
    raw[field] = value
    write(batch / runner.STATE_FILENAME, raw)
    with pytest.raises(ValueError, match="状态|schema|计数"):
        runner.load_or_create_state(batch, policy)


def ready(env, capsys):
    action = approve(env, capsys)
    accept_content(env, action, capsys)
    for index in range(6):
        next_image(env, capsys, (index * 30, 40, 90))
    runner, policy, batch, items, state = env
    assert runner.main(["next", "--batch", str(batch)]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "LOCAL_WORK_REQUIRED"
    return runner.load_or_create_state(batch, policy)


def fake_network(runner, monkeypatch, posts):
    def submit(item, key, dry_run):
        digest = runner._load_autodl().submit_payload(item / "_工作文件/任务状态/提交请求.json", dry_run=True)["request_hash"]
        if dry_run:
            return {"request_hash": digest, "dry_run": True}
        posts.append(runner._attempt_key(item))
        return {"request_hash": digest, "task_id": f"task-{len(posts)}", "response": {"code": 0}}
    monkeypatch.setattr(runner, "_submit_item", submit)
    monkeypatch.setattr(runner, "_poll_item", lambda *a, **k: {"status": "poll_timeout"})


def test_manifest_binds_payload_and_accounts_reservation_spend(setup_batch, capsys, monkeypatch):
    runner, policy, batch, items, _ = setup_batch
    state = ready(setup_batch, capsys)
    posts = []
    fake_network(runner, monkeypatch, posts)
    payload_path = items[0] / "_工作文件/任务状态/提交请求.json"
    original = json.loads(payload_path.read_text(encoding="utf-8"))
    changed = dict(original, resolution="2K")
    write(payload_path, changed)
    with pytest.raises(PermissionError, match="配置|批准"):
        runner.run_autodl_item(batch, items[0], state, api_key="offline")
    assert posts == []
    write(payload_path, original)
    runner.run_autodl_item(batch, items[0], state, api_key="offline")
    runner.run_autodl_item(batch, items[1], state, api_key="offline")
    assert posts == ["V001:V01", "V002:V01"]
    assert sum(float(v["cost"]) for v in state.budget_ledger.values()) == 6
    assert {row["status"] for row in state.budget_ledger.values()} == {"spent"}
    assert (items[0] / "_工作文件/任务状态/AutoDL提交结果.json").is_file()
    assert (items[0] / "_工作文件/任务状态/查询结果.json").is_file()


def test_v02_approval_clears_completion_and_executes_exactly_once(setup_batch, capsys, monkeypatch):
    runner, policy, batch, items, _ = setup_batch
    state = ready(setup_batch, capsys)
    posts = []
    fake_network(runner, monkeypatch, posts)
    runner.run_autodl_item(batch, items[0], state, api_key="offline")
    state.completed_nodes["V001"] = ["content", "video:V01"]
    runner._route_video_failures(batch, state, {"V001": "user failed"})
    assert runner.main(["approve-rerun", "--batch", str(batch), "--video-id", "V001", "--approved-cost", "0.01"]) == 2
    capsys.readouterr()
    assert runner._item_retry_count(items[0]) == 0
    assert runner.main(["approve-rerun", "--batch", str(batch), "--video-id", "V001", "--approved-cost", "3.00"]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "LOCAL_WORK_REQUIRED"
    state = runner.load_or_create_state(batch, policy)
    assert not runner._video_complete(items[0], state)
    runner.run_autodl_item(batch, items[0], state, api_key="offline")
    runner.run_autodl_item(batch, items[0], state, api_key="offline")
    assert posts == ["V001:V01", "V001:V02"]
    assert len(state.budget_ledger) == 2
    assert (items[0] / "_工作文件/历史版本/视频版本/V01_初次生成/提交请求.json").is_file()


def test_idempotent_image_receipt_and_raw_normalized_evidence(setup_batch, capsys):
    runner, policy, batch, items, _ = setup_batch
    initial = approve(setup_batch, capsys)
    accept_content(setup_batch, initial, capsys)
    action = next_image(setup_batch, capsys)
    state = runner.load_or_create_state(batch, policy)
    before = copy.deepcopy(state.image_calls_by_video)
    assert runner.main(["accept-image", "--batch", str(batch), "--video-id", "V001", "--artifact", action["artifact"], "--source", action["output_path"], "--action-id", action["action_id"]]) == 0
    capsys.readouterr()
    restored = runner.load_or_create_state(batch, policy)
    assert restored.image_calls_by_video == before
    assert restored.model_calls_by_video == {}
    technical = json.loads((items[0] / "_工作文件/验收记录/分镜候选_技术检查.json").read_text(encoding="utf-8"))
    assert technical["source_size"] == [2160, 3840]
    assert technical["target_size"] == [2160, 3840]
    assert technical["source_size"] == technical["target_size"]


def test_failed_image_accept_counts_retry_and_other_item_continues(setup_batch, capsys):
    runner, policy, batch, items, _ = setup_batch
    accept_content(setup_batch, approve(setup_batch, capsys), capsys)
    for attempt in range(2):
        runner.main(["next", "--batch", str(batch)])
        action = json.loads(capsys.readouterr().out)
        Path(action["output_path"]).write_bytes(b"broken")
        runner.main(["accept-image", "--batch", str(batch), "--video-id", "V001", "--artifact", action["artifact"], "--source", action["output_path"], "--action-id", action["action_id"]])
        capsys.readouterr()
    state = runner.load_or_create_state(batch, policy)
    assert state.image_failures["V001:分镜图.png"] == 2
    assert state.image_calls_by_video["V001"] == 2
    action = runner.next_action(batch, state, policy)
    assert action["video_id"] == "V002"


def test_replaced_candidate_cannot_be_promoted(setup_batch, capsys):
    runner, policy, batch, items, _ = setup_batch
    ready(setup_batch, capsys)
    item = items[0]
    candidate = item / "_工作文件/生成过程/视频候选.mp4"
    candidate.write_bytes(b"good-previously-decoded")
    original = runner._sha256(candidate)
    runner._persist_video_evidence(item, {"ok": True, "full_decode": True, "sha256": original, "candidate": str(candidate), "version": "V01"})
    candidate.write_bytes(b"corrupted-replacement")
    result = batch / "review.json"
    write(result, {"items": [{"video_id": "V001", "decision": "passed", "artifacts": {"视频.mp4": {"source_path": str(candidate), "sha256": runner._sha256(candidate)}}}]})
    with pytest.raises(ValueError, match="技术检查|哈希"):
        runner._promote_passed_review_outputs(batch, result, module("workflow_cli"))
    assert not list(item.glob("*.mp4"))


@pytest.mark.parametrize("crash", [False, True])
def test_cross_process_paid_claim_is_exclusive_and_stale_claim_fails_closed(setup_batch, capsys, crash):
    runner, policy, batch, items, _ = setup_batch
    ready(setup_batch, capsys)
    script = '''
import importlib.util, json, os, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("runner", sys.argv[1])
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
batch = Path(sys.argv[2]); item = r._video_items(batch)[0]
policy = r._load_policy_module().load_policy(Path(sys.argv[1]).parents[1])
state = r.load_or_create_state(batch, policy)
def submit(item, key, dry_run):
    if dry_run: return {"request_hash":"h"}
    with (batch / "post-count.txt").open("a", encoding="utf-8") as f: f.write("post\\n")
    if sys.argv[3] == "True": os._exit(23)
    time.sleep(0.2)
    return {"request_hash":"h", "task_id":"once"}
r._submit_item = submit
r._poll_item = lambda *a, **k: {"status":"poll_timeout"}
try: print(json.dumps(r.run_autodl_item(batch, item, state, api_key="offline")))
except RuntimeError as exc: print(json.dumps({"busy":str(exc)}))
'''
    command = [sys.executable, "-c", script, str(SKILL / "scripts/pipeline_runner.py"), str(batch), str(crash)]
    first = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    second = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    one, err_one = first.communicate(timeout=20)
    two, err_two = second.communicate(timeout=20)
    assert first.returncode in {0, 23}, err_one.decode()
    assert second.returncode in {0, 23}, err_two.decode()
    assert (batch / "post-count.txt").read_text(encoding="utf-8").splitlines() == ["post"]
    again = subprocess.run(command, capture_output=True, check=True, text=True, encoding="utf-8")
    result = json.loads(again.stdout)
    assert result["status"] == ("RECONCILIATION_REQUIRED" if crash else "poll_timeout")
    assert (batch / "post-count.txt").read_text(encoding="utf-8").splitlines() == ["post"]


def test_policy_rejects_malformed_limits_and_review_override(tmp_path):
    policy = module("pipeline_policy")
    value = policy.load_policy(SKILL)
    value["image"]["human_review"] = True
    write(tmp_path / "pipeline_policy.json", value)
    with pytest.raises(ValueError):
        policy.load_policy(tmp_path)


def test_remaining_v01_failure_stays_in_rerun_queue(setup_batch, capsys, monkeypatch):
    runner, policy, batch, items, _ = setup_batch
    state = ready(setup_batch, capsys)
    for item in items:
        record_offline_submission(runner, item, item.name[:4])
    runner._route_video_failures(batch, state, {"V001": "bad one", "V002": "bad two"})
    assert runner.main(["approve-rerun", "--batch", str(batch), "--video-id", "V001", "--approved-cost", "3"]) == 0
    capsys.readouterr()
    state = runner.load_or_create_state(batch, policy)
    assert state.item_failures["V002"]["kind"] == "video"
    def execute(batch, item, state, **kwargs):
        record_offline_submission(runner, item, "offline-v02")
        candidate = item / "_工作文件/生成过程/视频候选.mp4"
        candidate.write_bytes(b"V02")
        return {"ok": True, "candidate": str(candidate), "technical": {"ok": True, "full_decode": True, "sha256": runner._sha256(candidate)}}
    monkeypatch.setattr(runner, "run_autodl_item", execute)
    result = runner.run_local_until_gate(batch, state, policy)
    assert result["kind"] == "USER_RERUN_APPROVAL_REQUIRED"
    assert result["video_ids"] == ["V002"]


def test_runtime_errors_persist_at_item_scope_and_other_item_finishes(setup_batch, capsys, monkeypatch):
    runner, policy, batch, items, _ = setup_batch
    state = ready(setup_batch, capsys)
    def execute(batch, item, state, **kwargs):
        if item == items[0]:
            raise ValueError("video validation failed")
        record_offline_submission(runner, item)
        candidate = item / "_工作文件/生成过程/视频候选.mp4"
        candidate.write_bytes(b"good")
        return {"ok": True, "candidate": str(candidate), "technical": {"ok": True, "full_decode": True, "sha256": runner._sha256(candidate)}}
    monkeypatch.setattr(runner, "run_autodl_item", execute)
    result = runner.run_local_until_gate(batch, state, policy)
    restored = runner.load_or_create_state(batch, policy)
    assert runner._video_complete(items[1], restored)
    assert restored.item_failures["V001"]["reason"] == "video validation failed"
    assert result["kind"] == "USER_FINAL_REVIEW_REQUIRED"


def test_docs_do_not_reintroduce_image_review_or_unreserved_work():
    workflow = (SKILL / "references/workflow.md").read_text(encoding="utf-8")
    startup = (SKILL / "references/startup-checklist.md").read_text(encoding="utf-8")
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "学习确认模式由用户通过" not in workflow
    assert "生图文字不准确时" not in workflow
    assert "分镜图最大尝试次数：3" not in startup
    assert "--action-id" in workflow
    assert "LOCAL_WORK_REQUIRED" in skill
    assert "DRY_RUN_COMPLETE" in skill


def test_diagnostics_and_corrections_have_distinct_bounded_counters(setup_batch):
    runner, policy, batch, items, state = setup_batch
    state.status = "RUNNING_AUTOMATICALLY"
    action = runner._reserve_action(batch, state, policy, {"kind": "MODEL_DIAGNOSTIC_REQUIRED", "video_id": "V001"}, "diagnostic")
    runner._finish_action(state, state.model_actions[action["action_id"]], "diagnostic", {"ok": True})
    runner._reserve_action(batch, state, policy, {"kind": "BATCH_CONTENT_REQUIRED"}, "content_correction")
    assert state.model_usage == {"diagnostic": 1, "content_correction": 1}
    assert state.image_calls_by_video == {}
    row = state.model_actions[state.pending_action["action_id"]]
    runner._finish_action(state, row, "correction", {"ok": True})
    with pytest.raises(runner.ModelBudgetExceeded):
        runner._reserve_action(batch, state, policy, {"kind": "MODEL_DIAGNOSTIC_REQUIRED", "video_id": "V001"}, "diagnostic")


def test_diagnostic_cli_reserves_before_execution_and_accepts_once(setup_batch, capsys):
    runner, policy, batch, items, _ = setup_batch
    ready(setup_batch, capsys)
    assert runner.main(["reserve-diagnostic", "--batch", str(batch), "--video-id", "V001", "--reason", "下载后需定位本地错误"]) == 0
    action = json.loads(capsys.readouterr().out)
    assert action["kind"] == "MODEL_DIAGNOSTIC_REQUIRED"
    assert runner.load_or_create_state(batch, policy).model_usage["diagnostic"] == 1
    result_path = Path(action["output_path"])
    write(result_path, {"summary": "检查本地解码日志", "paid_retry": False})
    args = ["accept-diagnostic", "--batch", str(batch), "--action-id", action["action_id"], "--result", str(result_path)]
    assert runner.main(args) == 0
    one = json.loads(capsys.readouterr().out)
    assert runner.main(args) == 0
    assert json.loads(capsys.readouterr().out) == one
    assert runner.load_or_create_state(batch, policy).model_usage["diagnostic"] == 1


def test_raw_paid_response_survives_missing_task_id(tmp_path, monkeypatch):
    client = module("autodl_h3")
    payload = tmp_path / "request.json"
    write(payload, {"prompt": "一镜到底，连续平稳运镜，完整双人对话口播", "duration": 15, "resolution": "768p竖", "first_frame": "data:image/png;base64,AAAA", "last_frame": "data:image/png;base64,BBBB"})
    raw = {"code": 42, "msg": "provider rejected", "request_id": "r"}
    monkeypatch.setattr(client, "_json_request", lambda *a, **k: raw)
    evidence = tmp_path / "raw-response.json"
    with pytest.raises(ValueError, match="task_id"):
        client.submit_payload(payload, api_key="offline", confirm_paid=True, response_path=evidence)
    assert json.loads(evidence.read_text(encoding="utf-8")) == raw


def test_invalid_dry_run_does_not_write_command_errors_to_production(setup_batch, capsys):
    runner, policy, batch, items, state = setup_batch
    approve(setup_batch, capsys)
    before = (batch / runner.STATE_FILENAME).read_bytes()
    write(items[0] / "_工作文件/任务状态/提交请求.json", {"broken": True})
    runner.main(["run-local", "--batch", str(batch), "--dry-run"])
    result = json.loads(capsys.readouterr().out)
    assert result["kind"] == "DRY_RUN_COMPLETE"
    assert (batch / runner.STATE_FILENAME).read_bytes() == before


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires local media tools")
def test_real_local_video_passes_full_decode_and_hash_binding(tmp_path):
    candidate = tmp_path / "real.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=1440x2560:r=1:d=15", "-f", "lavfi", "-i", "sine=frequency=440:duration=15", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(candidate)], check=True, capture_output=True, timeout=30)
    runner = module()
    evidence = runner.validate_video_file(candidate, "2K")
    assert evidence["full_decode"] is True
    assert evidence["sha256"] == runner._sha256(candidate)
    assert evidence["has_audio"] is True


def test_retry_notice_is_not_an_unreserved_external_generation_action(setup_batch):
    runner, policy, batch, items, state = setup_batch
    result = runner.record_image_failure(state, video_id="V001", artifact="分镜图.png", reason="bad download")
    assert result["kind"] == "IMAGE_FAILURE_RECORDED"
    assert result["retry_pending"] is True
    assert "action_id" not in result


def test_release_source_parity_and_security():
    with zipfile.ZipFile(ROOT / "release/product-video-pipeline-v1.7.0.zip") as archive:
        names = archive.namelist()
        tracked = subprocess.run(["git", "-c", "core.quotePath=false", "ls-files", "--", "skill-package/product-video-pipeline"], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
        expected = {"product-video-pipeline/" + path.split("skill-package/product-video-pipeline/", 1)[1] for path in tracked}
        assert {name for name in names if not name.endswith("/")} == expected
        for name in names:
            if name.endswith("/"):
                continue
            relative = Path(name).relative_to("product-video-pipeline")
            assert ".." not in relative.parts
            assert not any(part in {"__pycache__", ".env", "流水线状态.json", "任务信息.json"} for part in relative.parts)
            assert relative.suffix != ".pyc"
            source = SKILL / relative
            assert source.is_file()
            assert archive.read(name).replace(b"\r\n", b"\n") == source.read_bytes().replace(b"\r\n", b"\n"), f"stale archive entry: {relative}"
