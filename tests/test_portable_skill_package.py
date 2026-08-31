import importlib.util
import json
import os
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skill-package" / "product-video-pipeline"


def load_script(name: str):
    path = SKILL_ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_skill_entrypoint_is_cross_agent_and_has_no_stale_workflow():
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "name: product-video-pipeline" in text
    assert "description: Use when" in text
    assert "Codex" in text
    assert "WorkBuddy" in text
    assert "Hermes" in text
    assert "references/workflow.md" in text
    assert "references/startup-checklist.md" in text
    assert "10秒" not in text
    assert "3分镜" not in text
    assert "1080P" not in text
    assert "¥0.10/秒" not in text


def test_startup_communication_is_complete_before_any_task_action():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    startup = (SKILL_ROOT / "references" / "startup-checklist.md").read_text(
        encoding="utf-8"
    )

    assert "每次任务" in skill
    assert "第一步" in skill
    assert "你需要提供的内容" in skill
    assert "本次配置明细" in skill
    assert "请你回复" in skill
    for phrase in (
        "你需要提供的内容",
        "本次配置明细",
        "请你回复",
        "每次任务",
        "未收到用户明确回复前",
        "不扫描产品素材",
        "可复制填写",
        "已提供",
        "待确认",
        "需要提供",
    ):
        assert phrase in startup


def test_skill_package_contains_required_portable_resources():
    required = {
        "agents/openai.yaml",
        "profiles/爱优护电动轮椅_淘宝天猫光合.json",
        "references/workflow.md",
        "references/startup-checklist.md",
        "references/content-contract.md",
        "references/ayh-wheelchair-rules.md",
        "references/autodl-h3.md",
        "references/review-learning.md",
        "references/install.md",
        "references/image-generation-routing.md",
        "references/automatic-learning-rules.md",
        "requirements.txt",
        "scripts/workflow_cli.py",
        "scripts/autodl_h3.py",
        "scripts/render_cover.py",
        "scripts/self_test.py",
    }
    present = {
        path.relative_to(SKILL_ROOT).as_posix()
        for path in SKILL_ROOT.rglob("*")
        if path.is_file()
    }
    assert required <= present


def test_image_generation_routing_is_fixed_and_cross_agent_safe():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    routing = (SKILL_ROOT / "references" / "image-generation-routing.md").read_text(encoding="utf-8")

    assert "references/image-generation-routing.md" in skill
    assert "本机 Codex 界面 → ChatGPT 网页端 → 第三方 API 生图" in routing
    assert "不得调用当前智能体自身的原生生图能力" in routing
    assert "2160×3840" in routing
    assert "SHA-256" in routing
    assert "不得跳级" in routing
    assert "不得要求用户提供账号密码" in routing
    assert "dry-run" in routing
    assert "第三个候选仍不合格" in routing


def test_clean_first_level_and_work_file_rules_are_documented():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    workflow = (SKILL_ROOT / "references" / "workflow.md").read_text(encoding="utf-8")
    autodl = (SKILL_ROOT / "references" / "autodl-h3.md").read_text(encoding="utf-8")
    review = (SKILL_ROOT / "references" / "review-learning.md").read_text(encoding="utf-8")

    assert "第一级只保留" in skill
    for name in (
        "视频.mp4",
        "封面图.png",
        "发布正文.txt",
        "话题标签.txt",
        "标题.txt",
        "分镜图.png",
        "尾帧图.png",
    ):
        assert name in skill
    for category in ("_工作文件/任务状态", "_工作文件/生成过程", "_工作文件/验收记录", "_工作文件/历史版本"):
        assert category in workflow
    assert "_工作文件/任务状态/任务信息.json" in autodl
    assert '--payload "_工作文件/任务状态/提交请求.json"' in autodl
    assert '--state "_工作文件/任务状态/提交预览.json"' in autodl
    assert '--state "_工作文件/任务状态/AutoDL提交结果.json"' in autodl
    assert "_工作文件/验收记录/自动验收报告.md" in review
    assert "--title-file _工作文件/生成过程/封面标题.txt" in skill
    assert "--title-file _工作文件/生成过程/封面标题.txt" in workflow
    assert (SKILL_ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.6.0"


def test_explicit_approval_rules_gate_every_root_output_by_hash():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    workflow = (SKILL_ROOT / "references" / "workflow.md").read_text(encoding="utf-8")
    contract = (SKILL_ROOT / "references" / "content-contract.md").read_text(encoding="utf-8")
    review = (SKILL_ROOT / "references" / "review-learning.md").read_text(encoding="utf-8")
    combined = "\n".join((skill, workflow, contract, review))

    assert "产出验收记录.json" in combined
    assert "明确通过" in skill
    assert "SHA-256" in workflow
    assert "没有明确通过" in workflow and "一级目录不保留" in workflow
    assert "review-output" in skill and "audit-outputs" in skill
    assert "自动验收" in review and "不能" in review and "最终晋升" in review
    assert "_工作文件/生成过程/标题.txt" in contract
    assert "_工作文件/生成过程/发布正文.txt" in contract
    assert "_工作文件/生成过程/话题标签.txt" in contract
    assert (SKILL_ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.6.0"


def test_v1_5_release_contains_unified_first_last_frame_skill():
    archive = REPO_ROOT / "release" / "product-video-pipeline-v1.5.0.zip"
    assert archive.is_file()
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert "product-video-pipeline/SKILL.md" in names
        assert "product-video-pipeline/VERSION" in names
        assert "product-video-pipeline/scripts/autodl_h3.py" in names
        assert "product-video-pipeline/references/autodl-h3.md" in names
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
        assert bundle.read("product-video-pipeline/VERSION").decode("utf-8").strip() == "1.5.0"
        skill = bundle.read("product-video-pipeline/SKILL.md").decode("utf-8")
        assert "first_frame" in skill and "last_frame" in skill
        assert "所有新视频固定使用 `minimax_h3_lightx2v`" in skill


def test_v1_6_release_contains_seven_root_deliverables():
    archive = REPO_ROOT / "release" / "product-video-pipeline-v1.6.0.zip"
    assert archive.is_file()
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert "product-video-pipeline/SKILL.md" in names
        assert "product-video-pipeline/VERSION" in names
        assert "product-video-pipeline/scripts/workflow_cli.py" in names
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
        assert bundle.read("product-video-pipeline/VERSION").decode("utf-8").strip() == "1.6.0"
        skill = bundle.read("product-video-pipeline/SKILL.md").decode("utf-8")
        for artifact in (
            "标题.txt",
            "发布正文.txt",
            "话题标签.txt",
            "分镜图.png",
            "尾帧图.png",
            "封面图.png",
            "视频.mp4",
        ):
            assert artifact in skill


def test_automatic_learning_reference_is_complete_and_routed():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    learning = (SKILL_ROOT / "references" / "automatic-learning-rules.md").read_text(
        encoding="utf-8"
    )
    assert "references/automatic-learning-rules.md" in skill
    assert "用户反馈 → 自动复盘 → V02验证 → 自动升级正式规则 → 下次任务强制加载并执行" in learning
    assert "record-issue" in learning
    assert "validate-learning" in learning
    assert "prepare-node-rules" in learning
    assert "start-rerun" in learning
    assert "failed" in learning and "inconclusive" in learning
    assert "自动模式只读取正式规则" in learning


def test_runtime_scans_first_level_allocates_and_creates_independent_library(tmp_path):
    runtime = load_script("workflow_cli.py")
    product = tmp_path / "测试产品甲"
    product.mkdir()
    Image.new("RGB", (64, 64), "white").save(product / "正侧45度.png")
    nested = product / "不要读取"
    nested.mkdir()
    Image.new("RGB", (64, 64), "black").save(nested / "嵌套图.png")
    cover_refs = tmp_path / "封面图参考"
    cover_refs.mkdir()
    Image.new("RGB", (64, 64), "navy").save(cover_refs / "参考.png")
    knowledge = tmp_path / "共享知识"

    context = runtime.initialize_batch(
        product_dir=product,
        product_name="测试产品甲",
        selling_points=("A", "B", "C", "D", "E"),
        total_videos=23,
        run_mode="learning",
        resolution="768P",
        max_budget_yuan="200",
        cover_reference_dir=cover_refs,
        knowledge_dir=knowledge,
        now=datetime(2026, 8, 26, 12, 0, 0),
    )

    assert [path.name for path in context.product_images] == ["正侧45度.png"]
    assert [item.selling_point for item in context.items].count("A") == 5
    assert [item.selling_point for item in context.items].count("E") == 4
    assert len(context.items) == 23
    assert (context.batch_dir / "启动确认单.json").exists()
    assert (context.batch_dir / "批次任务表.json").exists()
    library_files = list((knowledge / "产品卖点库").glob("*.json"))
    assert len(library_files) == 1
    library = json.loads(library_files[0].read_text(encoding="utf-8"))
    assert library["product_name"] == "测试产品甲"
    assert {point["content"] for point in library["selling_points"]} == {"A", "B", "C", "D", "E"}
    first_item = context.items[0].project_dir
    assert (first_item / "_工作文件" / "任务状态" / "任务信息.json").exists()
    assert all((first_item / "_工作文件" / category).is_dir() for category in runtime.WORK_CATEGORIES)
    assert not (first_item / "任务信息.json").exists()
    assert not (first_item / "失败版本").exists()
    assert not (first_item / "视频版本").exists()


def test_organize_item_dir_keeps_only_deliverables_and_categorizes_work_files(tmp_path):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    item.mkdir()
    deliverables = {
        "视频.mp4",
        "封面图.png",
        "发布正文.txt",
        "话题标签.txt",
        "标题.txt",
        "分镜图.png",
        "尾帧图.png",
    }
    assert runtime.DELIVERABLE_NAMES == deliverables
    for name in deliverables:
        (item / name).write_bytes(name.encode("utf-8"))
    (item / "发布正文.md").write_text("旧格式正文与标签", encoding="utf-8")
    (item / "任务信息.json").write_text("{}", encoding="utf-8")
    (item / "查询结果.json").write_text("{}", encoding="utf-8")
    (item / "视频提示词.txt").write_text("一镜到底", encoding="utf-8")
    (item / "自动验收报告.md").write_text("通过", encoding="utf-8")
    (item / "视频_V02.mp4").write_bytes(b"old-video")
    (item / "失败版本").mkdir()
    (item / "失败版本" / "失败.mp4").write_bytes(b"failed")
    (item / "视频版本").mkdir()
    (item / "视频版本" / "V01.mp4").write_bytes(b"v01")

    before = sorted(path.name for path in item.iterdir())
    preview = runtime.organize_item_dir(item, dry_run=True)
    assert preview["moved"]
    assert sorted(path.name for path in item.iterdir()) == before

    result = runtime.organize_item_dir(item)
    assert result["conflicts"] == []
    assert result["root_clean"] is True
    assert result["remaining_forbidden"] == []
    assert {path.name for path in item.iterdir()} == {"_工作文件"}
    assert len(result["output_audit"]["demoted"]) == 7
    assert (item / "_工作文件" / "任务状态" / "任务信息.json").exists()
    assert (item / "_工作文件" / "任务状态" / "查询结果.json").exists()
    assert (item / "_工作文件" / "生成过程" / "视频提示词.txt").exists()
    assert (item / "_工作文件" / "验收记录" / "自动验收报告.md").exists()
    assert (item / "_工作文件" / "历史版本" / "视频_V02.mp4").exists()
    assert (item / "_工作文件" / "历史版本" / "旧格式" / "发布正文.md").exists()
    assert (item / "_工作文件" / "历史版本" / "失败版本" / "失败.mp4").exists()
    assert (item / "_工作文件" / "历史版本" / "视频版本" / "V01.mp4").exists()
    demoted_files = list((item / "_工作文件" / "历史版本" / "未通过或待验收").iterdir())
    assert {path.read_bytes() for path in demoted_files} == {name.encode("utf-8") for name in deliverables}

    repeated = runtime.organize_item_dir(item)
    assert repeated["moved"] == []
    assert repeated["conflicts"] == []


def test_organize_item_dir_stops_before_moving_when_target_conflicts(tmp_path):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    target = item / "_工作文件" / "任务状态" / "任务信息.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"new-state")
    source = item / "任务信息.json"
    source.write_bytes(b"legacy-state")
    process_file = item / "视频提示词.txt"
    process_file.write_text("不能提前移动", encoding="utf-8")

    with pytest.raises(FileExistsError, match="任务信息.json"):
        runtime.organize_item_dir(item)

    assert source.read_bytes() == b"legacy-state"
    assert target.read_bytes() == b"new-state"
    assert process_file.exists()


def test_organize_item_dir_preserves_identical_file_and_directory_duplicates(tmp_path):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    duplicate_file = item / "任务信息.json"
    target_file = item / "_工作文件" / "任务状态" / "任务信息.json"
    duplicate_dir = item / "失败版本"
    target_dir = item / "_工作文件" / "历史版本" / "失败版本"
    target_file.parent.mkdir(parents=True)
    target_file.write_bytes(b"same")
    duplicate_file.write_bytes(b"same")
    duplicate_dir.mkdir()
    target_dir.mkdir(parents=True)

    result = runtime.organize_item_dir(item)

    duplicate_root = item / "_工作文件" / "历史版本" / "重复项"
    assert (duplicate_root / "任务信息.json").read_bytes() == b"same"
    assert (duplicate_root / "失败版本").is_dir()
    assert result["root_clean"] is True
    assert len(result["duplicates"]) == 2


def test_batch_organizer_only_visits_video_items_and_preserves_batch_files(tmp_path):
    runtime = load_script("workflow_cli.py")
    batch = tmp_path / "20260828_批次001"
    item = batch / "V001_卖点_待生成"
    item.mkdir(parents=True)
    (item / "查询结果.json").write_text("{}", encoding="utf-8")
    batch_table = batch / "批次任务表.json"
    batch_table.write_text("{}", encoding="utf-8")
    confirmation = batch / "启动确认单.json"
    confirmation.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="单条任务目录"):
        runtime.organize_item_dir(batch, dry_run=True)

    result = runtime.organize_batch_dir(batch)

    assert result["items"][0]["root_clean"] is True
    assert batch_table.exists() and confirmation.exists()
    assert item.exists()
    assert (item / "_工作文件" / "任务状态" / "查询结果.json").exists()
    assert not (batch / "_工作文件").exists()


def test_real_world_audio_review_names_are_classified_as_review_evidence(tmp_path):
    runtime = load_script("workflow_cli.py")
    candidate = tmp_path / "口播音轨验收_双角色清晰版.md"
    candidate.write_text("通过", encoding="utf-8")

    category, relative = runtime.classify_legacy_entry(candidate)

    assert category == "验收记录"
    assert relative.name == candidate.name


def test_artifact_decision_validates_name_decision_user_and_source_boundary(tmp_path):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    candidate = item / "_工作文件" / "生成过程" / "候选视频.mp4"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"candidate")
    outside = tmp_path / "外部视频.mp4"
    outside.write_bytes(b"outside")
    root_output = item / "视频.mp4"
    root_output.write_bytes(b"root")

    with pytest.raises(ValueError, match="产出名称"):
        runtime.record_artifact_decision(item, "实验.mp4", candidate, "passed", "用户", "确认通过")
    with pytest.raises(ValueError, match="验收决定"):
        runtime.record_artifact_decision(item, "视频.mp4", candidate, "pending", "用户", "等待")
    with pytest.raises(ValueError, match="确认人"):
        runtime.record_artifact_decision(item, "视频.mp4", candidate, "passed", "", "确认通过")
    with pytest.raises(ValueError, match="反馈"):
        runtime.record_artifact_decision(item, "视频.mp4", candidate, "passed", "用户", "")
    with pytest.raises(ValueError, match="任务目录内"):
        runtime.record_artifact_decision(item, "视频.mp4", outside, "passed", "用户", "确认通过")
    with pytest.raises(ValueError, match="不能是一级固定产出"):
        runtime.record_artifact_decision(item, "视频.mp4", root_output, "passed", "用户", "确认通过")


def test_approval_events_are_append_only_and_latest_event_wins(tmp_path):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    candidate = item / "_工作文件" / "生成过程" / "候选封面.png"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"cover")

    passed = runtime.record_artifact_decision(
        item,
        "封面图.png",
        candidate,
        "passed",
        "用户",
        "封面确认通过",
        now=datetime.fromisoformat("2026-08-28T12:00:00+08:00"),
    )
    revoked = runtime.record_artifact_decision(
        item,
        "封面图.png",
        candidate,
        "revoked",
        "用户",
        "发现产品结构问题，撤销",
        now=datetime.fromisoformat("2026-08-28T12:05:00+08:00"),
    )

    events = runtime.load_approval_events(item)
    latest = runtime.latest_artifact_decision(events, "封面图.png", passed["sha256"])
    assert len(events) == 2
    assert passed["event_id"] != revoked["event_id"]
    assert latest["event_id"] == revoked["event_id"]
    assert latest["decision"] == "revoked"
    assert passed["submitted_source_path"] == "_工作文件/生成过程/候选封面.png"
    assert passed["source_path"].startswith("_工作文件/历史版本/验收候选/封面图/")
    assert runtime.approval_log_path(item).exists()


def test_latest_artifact_decision_uses_append_order_even_if_clock_moves_backward(tmp_path):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    candidate = item / "_工作文件" / "生成过程" / "候选封面.png"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"cover")
    passed = runtime.record_artifact_decision(
        item, "封面图.png", candidate, "passed", "用户", "通过",
        now=datetime.fromisoformat("2026-08-28T12:00:00+08:00"),
    )
    revoked = runtime.record_artifact_decision(
        item, "封面图.png", candidate, "revoked", "用户", "撤销",
        now=datetime.fromisoformat("2026-08-28T11:00:00+08:00"),
    )

    latest = runtime.latest_artifact_decision(runtime.load_approval_events(item), "封面图.png", passed["sha256"])

    assert latest["event_id"] == revoked["event_id"]


def test_concurrent_artifact_decisions_do_not_lose_events(tmp_path, monkeypatch):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    candidate = item / "_工作文件" / "生成过程" / "候选视频.mp4"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"video")
    original_write = runtime.atomic_write_json

    def slow_write(path, value):
        time.sleep(0.02)
        original_write(path, value)

    monkeypatch.setattr(runtime, "atomic_write_json", slow_write)
    same_time = datetime.fromisoformat("2026-08-28T12:00:00+08:00")
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(
                runtime.record_artifact_decision,
                item,
                "视频.mp4",
                candidate,
                "passed",
                f"用户{i}",
                "明确通过",
                same_time,
            )
            for i in range(8)
        ]
        for future in futures:
            future.result()

    assert len(runtime.load_approval_events(item)) == 8


def test_separate_processes_append_artifact_decisions_without_loss(tmp_path):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    candidate = item / "_工作文件" / "生成过程" / "候选视频.mp4"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"video")
    command_base = [
        sys.executable,
        str(SKILL_ROOT / "scripts" / "workflow_cli.py"),
        "review-output",
        "--item-dir",
        str(item),
        "--artifact",
        "视频.mp4",
        "--source",
        str(candidate.relative_to(item)),
        "--decision",
        "failed",
        "--feedback",
        "明确不通过",
    ]
    processes = [
        subprocess.Popen(command_base + ["--confirmed-by", f"用户{i}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for i in range(4)
    ]

    results = [process.communicate(timeout=20) + (process.returncode,) for process in processes]

    assert all(return_code == 0 for _stdout, _stderr, return_code in results)
    assert len(runtime.load_approval_events(item)) == 4


def test_promote_approved_artifact_archives_previous_root_and_keeps_candidate(tmp_path):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    candidate = item / "_工作文件" / "生成过程" / "最终候选标题.txt"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"approved-title")
    old_root = item / "标题.txt"
    old_root.write_bytes(b"old-title")
    event = runtime.record_artifact_decision(
        item,
        "标题.txt",
        candidate,
        "passed",
        "用户",
        "标题明确通过",
        now=datetime.fromisoformat("2026-08-28T13:00:00+08:00"),
    )

    promoted = runtime.promote_approved_artifact(item, event)

    assert promoted == old_root
    assert old_root.read_bytes() == b"approved-title"
    assert candidate.read_bytes() == b"approved-title"
    archived = list((item / "_工作文件" / "历史版本" / "已撤换产出").iterdir())
    assert len(archived) == 1
    assert archived[0].read_bytes() == b"old-title"
    assert runtime._sha256_file(old_root) == event["sha256"]


def test_first_and_tail_frames_require_independent_approval_and_hashes(tmp_path):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    process = item / "_工作文件" / "生成过程"
    process.mkdir(parents=True)
    first_candidate = process / "分镜候选.png"
    tail_candidate = process / "尾帧候选.png"
    first_candidate.write_bytes(b"accepted-first-frame")
    tail_candidate.write_bytes(b"independent-tail-frame")

    first_event = runtime.record_artifact_decision(
        item, "分镜图.png", first_candidate, "passed", "用户", "首帧明确通过"
    )
    tail_event = runtime.record_artifact_decision(
        item, "尾帧图.png", tail_candidate, "passed", "用户", "尾帧明确通过"
    )
    first_root = runtime.promote_approved_artifact(item, first_event)
    tail_root = runtime.promote_approved_artifact(item, tail_event)

    assert first_root.name == "分镜图.png"
    assert tail_root.name == "尾帧图.png"
    assert runtime._sha256_file(first_root) != runtime._sha256_file(tail_root)
    assert runtime.validated_promoted_artifact_path(item, "分镜图.png") == first_root
    assert runtime.validated_promoted_artifact_path(item, "尾帧图.png") == tail_root


def test_promote_rolls_back_previous_root_when_final_replace_fails(tmp_path, monkeypatch):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    candidate = item / "_工作文件" / "生成过程" / "最终候选标题.txt"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"approved-title")
    root_output = item / "标题.txt"
    root_output.write_bytes(b"old-title")
    event = runtime.record_artifact_decision(item, "标题.txt", candidate, "passed", "用户", "明确通过")
    original_replace = runtime.Path.replace

    def failing_replace(path, target):
        if path.name.startswith("标题.txt.tmp") and Path(target) == root_output:
            raise OSError("injected replace failure")
        return original_replace(path, target)

    monkeypatch.setattr(runtime.Path, "replace", failing_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        runtime.promote_approved_artifact(item, event)

    assert root_output.read_bytes() == b"old-title"
    assert not list(item.glob("标题.txt.tmp*"))


@pytest.mark.parametrize("decision", [None, "failed", "revoked"])
def test_audit_promoted_outputs_demotes_missing_failed_or_revoked_evidence(tmp_path, decision):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    candidate = item / "_工作文件" / "生成过程" / "候选正文.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"body")
    root_output = item / "发布正文.txt"
    root_output.write_bytes(b"body")
    if decision:
        runtime.record_artifact_decision(
            item,
            "发布正文.txt",
            candidate,
            decision,
            "用户",
            "明确不通过" if decision == "failed" else "明确撤销",
            now=datetime.fromisoformat("2026-08-28T13:05:00+08:00"),
        )

    result = runtime.audit_promoted_outputs(
        item,
        now=datetime.fromisoformat("2026-08-28T13:10:00+08:00"),
    )

    assert not root_output.exists()
    assert len(result["demoted"]) == 1
    archived = list((item / "_工作文件" / "历史版本" / "未通过或待验收").iterdir())
    assert len(archived) == 1
    assert archived[0].read_bytes() == b"body"


def test_audit_promoted_outputs_demotes_hash_changed_after_pass(tmp_path):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    candidate = item / "_工作文件" / "生成过程" / "候选分镜.png"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"approved-storyboard")
    event = runtime.record_artifact_decision(
        item,
        "分镜图.png",
        candidate,
        "passed",
        "用户",
        "分镜明确通过",
        now=datetime.fromisoformat("2026-08-28T13:20:00+08:00"),
    )
    runtime.promote_approved_artifact(item, event)
    (item / "分镜图.png").write_bytes(b"tampered")

    result = runtime.audit_promoted_outputs(item)

    assert not (item / "分镜图.png").exists()
    assert len(result["demoted"]) == 1
    assert list((item / "_工作文件" / "历史版本" / "未通过或待验收").iterdir())[0].read_bytes() == b"tampered"


def test_legacy_review_cannot_promote_and_audit_is_idempotent(tmp_path):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    review_dir = item / "_工作文件" / "验收记录"
    review_dir.mkdir(parents=True)
    (review_dir / "人工验收结果.md").write_text("结果：passed", encoding="utf-8")
    (item / "封面图.png").write_bytes(b"legacy-cover")

    first = runtime.audit_promoted_outputs(item)
    second = runtime.audit_promoted_outputs(item)

    assert len(first["demoted"]) == 1
    assert second["demoted"] == []
    assert not runtime.approval_log_path(item).exists()
    assert not (item / "封面图.png").exists()


def test_review_output_cli_accepts_relative_candidate_and_promotes_passed_file(tmp_path):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    relative = Path("_工作文件/生成过程/候选视频.mp4")
    candidate = item / relative
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"approved-video")

    exit_code = runtime.main(
        [
            "review-output",
            "--item-dir",
            str(item),
            "--artifact",
            "视频.mp4",
            "--source",
            str(relative),
            "--decision",
            "passed",
            "--confirmed-by",
            "用户",
            "--feedback",
            "视频明确通过",
        ]
    )

    assert exit_code == 0
    assert (item / "视频.mp4").read_bytes() == b"approved-video"


def test_audit_outputs_cli_dry_run_supports_batch_without_changes(tmp_path):
    runtime = load_script("workflow_cli.py")
    batch = tmp_path / "20260828_批次001"
    item = batch / "V001_卖点_待生成"
    item.mkdir(parents=True)
    root_output = item / "标题.txt"
    root_output.write_bytes(b"unapproved")

    exit_code = runtime.main(["audit-outputs", "--batch", str(batch), "--dry-run"])

    assert exit_code == 0
    assert root_output.exists()


def test_audit_outputs_cli_fails_when_fixed_output_path_is_a_directory(tmp_path):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    (item / "视频.mp4").mkdir(parents=True)

    exit_code = runtime.main(["audit-outputs", "--item-dir", str(item)])

    assert exit_code == 2
    assert (item / "视频.mp4").is_dir()


def test_organize_cli_propagates_output_audit_errors_and_root_is_not_clean(tmp_path, capsys):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_卖点_待生成"
    (item / "视频.mp4").mkdir(parents=True)

    exit_code = runtime.main(["organize", "--item-dir", str(item)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["root_clean"] is False
    assert "视频.mp4" in output["remaining_forbidden"]
    assert output["output_audit"]["errors"]


def test_content_validator_enforces_confirmed_ayh_contract():
    runtime = load_script("workflow_cli.py")
    profile = json.loads(
        (SKILL_ROOT / "profiles" / "爱优护电动轮椅_淘宝天猫光合.json").read_text(encoding="utf-8")
    )
    valid = {
        "video_id": "V001",
        "selling_point": "操作简单",
        "publish_title": "爸妈也能轻松上手的电动轮椅到底怎么样",
        "cover_title": "爸妈会操作",
        "people": [
            {"id": "P1", "identity": "老人", "gender": "女", "age_feel": "70岁左右", "position": "左侧", "action": "坐在轮椅上", "speaks": True},
            {"id": "P2", "identity": "家属", "gender": "女", "age_feel": "40岁左右", "position": "右侧", "action": "自然提问", "speaks": True},
        ],
        "storyboard_people": ["P1", "P2"],
        "script_segments": [
            {"start": 0, "end": 4, "speaker_id": "P2", "dialogue": "这个操作会不会很难？"},
            {"start": 4, "end": 11, "speaker_id": "P1", "dialogue": "操作很顺手，我自己就能开，家里人也省心。"},
            {"start": 11, "end": 15, "speaker_id": "P1", "dialogue": "用了爱优护电动轮椅后，出门更方便，可以了解一下。"},
        ],
        "storyboard_prompt": "竖屏9:16，固定正侧45度角，两位女性始终同框，不要任何文字。",
        "last_frame_prompt": "同尺寸合理尾帧，主体继续前进约1至1.5米，产品结构和人物保持一致。",
        "video_prompt": "一镜到底，连续平稳运镜，完整双人对话口播，轮椅沿直线缓慢前进，不要背景音乐。",
        "publish_body": "以前老人总担心操作复杂，家里人每次都要陪在旁边。用了爱优护电动轮椅后，老人自己很快就能上手，平时在小区出门顺手多了，家属照顾也省心。有同样出门需求的家庭，可以了解一下爱优护电动轮椅。",
        "hashtags": ["#爱优护电动轮椅", "#ainsnbot高端智能电动轮椅", "#电动轮椅", "#老人专用电动轮椅"],
    }
    assert runtime.validate_content_package(valid, profile) == []

    invalid = dict(valid)
    invalid["publish_title"] = "爸妈出门方便多了"
    invalid["storyboard_people"] = ["P1"]
    invalid["video_prompt"] = "轮椅转弯进入电梯，镜头环绕"
    invalid["script_segments"] = list(valid["script_segments"])
    invalid["script_segments"][-1] = {"start": 11, "end": 15, "speaker_id": "P1", "dialogue": "大家可以买。"}
    codes = set(runtime.validate_content_package(invalid, profile))
    assert {"title.required_term", "people.mismatch", "motion.turning_forbidden", "closing.missing_improvement_and_cta"} <= codes


def test_content_paths_keep_deliverables_at_root_and_process_files_nested(tmp_path):
    runtime = load_script("workflow_cli.py")
    item = tmp_path / "V001_操作简单_待生成"
    item.mkdir()
    package = {
        "video_id": "V001",
        "selling_point": "操作简单",
        "publish_title": "爸妈也能轻松上手的电动轮椅到底怎么样",
        "cover_title": "爸妈会操作",
        "people": [
            {"id": "P1", "identity": "老人", "gender": "女", "age_feel": "70岁左右", "position": "左侧", "action": "坐在轮椅上", "speaks": True},
            {"id": "P2", "identity": "家属", "gender": "女", "age_feel": "40岁左右", "position": "右侧", "action": "自然提问", "speaks": True},
        ],
        "storyboard_people": ["P1", "P2"],
        "script_segments": [
            {"start": 0, "end": 4, "speaker_id": "P2", "dialogue": "这个操作会不会很难？"},
            {"start": 4, "end": 11, "speaker_id": "P1", "dialogue": "操作很顺手，我自己就能开，家里人也省心。"},
            {"start": 11, "end": 15, "speaker_id": "P1", "dialogue": "用了爱优护电动轮椅后，出门更方便，可以了解一下。"},
        ],
        "storyboard_prompt": "竖屏4K，2160×3840，9:16，两位女性始终同框。",
        "last_frame_prompt": "同尺寸合理尾帧，主体继续前进约1至1.5米。",
        "video_prompt": "一镜到底，连续平稳运镜，完整双人对话口播，轮椅沿直线缓慢前进。",
        "publish_body": "以前老人总担心操作复杂，家里人每次都要陪在旁边。用了爱优护电动轮椅后，老人自己很快就能上手，平时在小区出门顺手多了，家属照顾也省心。有同样出门需求的家庭，可以了解一下爱优护电动轮椅。",
        "hashtags": ["#爱优护电动轮椅", "#ainsnbot高端智能电动轮椅", "#电动轮椅", "#老人专用电动轮椅"],
    }
    package_path = tmp_path / "content.json"
    package_path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
    profile = SKILL_ROOT / "profiles" / "爱优护电动轮椅_淘宝天猫光合.json"

    runtime.save_content_package(item, package_path, profile)

    assert not (item / "标题.txt").exists()
    assert not (item / "发布正文.txt").exists()
    assert not (item / "话题标签.txt").exists()
    assert (item / "_工作文件" / "生成过程" / "标题.txt").exists()
    body_candidate = item / "_工作文件" / "生成过程" / "发布正文.txt"
    hashtag_candidate = item / "_工作文件" / "生成过程" / "话题标签.txt"
    assert body_candidate.read_text(encoding="utf-8") == package["publish_body"] + "\n"
    assert hashtag_candidate.read_text(encoding="utf-8") == " ".join(package["hashtags"]) + "\n"
    assert not any(tag in body_candidate.read_text(encoding="utf-8") for tag in package["hashtags"])
    assert (item / "_工作文件" / "生成过程" / "策划内容.json").exists()
    assert (item / "_工作文件" / "生成过程" / "分镜提示词.txt").exists()
    assert (item / "_工作文件" / "生成过程" / "合理尾帧提示词.txt").exists()
    assert (item / "_工作文件" / "生成过程" / "视频提示词.txt").exists()
    assert not (item / "策划内容.json").exists()

    title_candidate = item / "_工作文件" / "生成过程" / "标题.txt"
    old_title = title_candidate.read_bytes()
    event = runtime.record_artifact_decision(item, "标题.txt", title_candidate, "passed", "用户", "旧标题明确通过")
    package["publish_title"] = "爱优护电动轮椅让爸妈日常操作更省心吗"
    package_path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")

    runtime.save_content_package(item, package_path, profile)
    runtime.promote_approved_artifact(item, event)

    assert title_candidate.read_bytes() != old_title
    assert (item / "标题.txt").read_bytes() == old_title
    archived_candidates = list((item / "_工作文件" / "历史版本" / "候选版本").rglob("*.txt"))
    assert any(path.read_bytes() == old_title for path in archived_candidates)


def test_autodl_client_dry_run_is_non_billable_and_task_id_parser_is_tolerant(tmp_path):
    client = load_script("autodl_h3.py")
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "prompt": "一镜到底，连续平稳运镜，完整双人对话口播",
                "duration": 15,
                "resolution": "768p竖",
                "first_frame": "data:image/png;base64,AAAA",
                "last_frame": "data:image/png;base64,BBBB",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    preview = client.submit_payload(payload_path, api_key="secret", dry_run=True)
    assert preview["dry_run"] is True
    assert preview["url"] == (
        "https://www.autodl.art/api/v1/comfyui/comfyui_workflow/"
        "minimax_h3_lightx2v_v5_15s"
    )
    assert preview["payload"]["duration"] == 15
    assert preview["payload"]["resolution"] == "768p竖"
    assert preview["payload"]["first_frame"].startswith("data:image/png;base64,")
    assert preview["payload"]["last_frame"].startswith("data:image/png;base64,")
    assert "aigc_watermark" not in preview["payload"]
    assert "secret" not in json.dumps(preview, ensure_ascii=False)
    assert client.extract_task_id({"task_id": "root-task"}) == "root-task"
    assert client.extract_task_id({"data": {"task_id": "nested-task"}}) == "nested-task"
    assert client._status({"data": {"status": "completed"}}) == "completed"


def test_autodl_client_can_preview_first_last_frame_workflow(tmp_path):
    client = load_script("autodl_h3.py")
    payload_path = tmp_path / "first-last.json"
    payload_path.write_text(
        json.dumps(
            {
                "prompt": "一镜到底，连续平稳运镜，完整双人对话口播",
                "duration": 15,
                "resolution": "768p竖",
                "first_frame": "data:image/png;base64,AAAA",
                "last_frame": "data:image/png;base64,BBBB",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    preview = client.submit_payload(
        payload_path,
        api_key="secret",
        dry_run=True,
        workflow_id="minimax_h3_lightx2v",
    )

    assert preview["url"].endswith("/minimax_h3_lightx2v")
    assert preview["payload"]["first_frame"] != preview["payload"]["last_frame"]


def test_autodl_client_rejects_legacy_multi_image_audio_workflow(tmp_path):
    client = load_script("autodl_h3.py")
    payload_path = tmp_path / "multi-image-audio.json"
    payload_path.write_text(
        json.dumps(
            {
                "prompt": "广角固定构图，轮椅缓慢直线行驶",
                "duration": 15,
                "resolution": "768p竖",
                "ref_image_0": "data:image/png;base64,AAAA",
                "ref_audio_0": "data:audio/wav;base64,BBBB",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="不支持的工作流 ID"):
        client.submit_payload(
            payload_path,
            api_key="secret",
            dry_run=True,
            workflow_id="minimax_h3_image_audio_to_video_v2_15s",
        )


def test_autodl_reference_uses_current_comfyui_workflow():
    text = (SKILL_ROOT / "references" / "autodl-h3.md").read_text(encoding="utf-8")
    assert "minimax_h3_lightx2v_v5_15s" in text
    assert "minimax_h3_lightx2v" in text
    assert "/api/v1/minimax/v2/video_generation" not in text
    assert "first_frame" in text
    assert "last_frame" in text
    assert "minimax_h3_image_audio_to_video_v2_15s" in text
    assert "不得用于新任务、V01 或 V02 提交" in text


def test_workflow_requires_video_to_match_accepted_storyboard_visuals():
    text = (SKILL_ROOT / "references" / "workflow.md").read_text(encoding="utf-8")
    assert "已通过分镜是视频画面的视觉基准" in text
    assert "人物完整度、产品角度、构图、亮度、曝光、白平衡和色温" in text
    assert "自动判为视频不合格" in text


def test_rules_require_single_shot_smooth_camera_and_complete_narration():
    workflow = (SKILL_ROOT / "references" / "workflow.md").read_text(encoding="utf-8")
    contract = (SKILL_ROOT / "references" / "content-contract.md").read_text(encoding="utf-8")
    review = (SKILL_ROOT / "references" / "review-learning.md").read_text(encoding="utf-8")
    wheelchair = (SKILL_ROOT / "references" / "ayh-wheelchair-rules.md").read_text(encoding="utf-8")

    assert "禁止切镜、跳切、转场" in workflow
    assert "缓慢、连续、平稳运镜" in workflow
    assert "最多49个汉字" in contract
    assert "自动精简" in contract
    assert "尾句被截断" in review
    assert "自动判为不合格" in review
    assert "全部台词按自然聊天语速在 15 秒内完整说完" in wheelchair


def test_first_last_frame_workflow_applies_core_rules_for_full_duration():
    workflow = (SKILL_ROOT / "references" / "workflow.md").read_text(encoding="utf-8")
    autodl = (SKILL_ROOT / "references" / "autodl-h3.md").read_text(encoding="utf-8")

    assert "整个0–15秒" in workflow
    assert "整个 0–15 秒" in autodl
    assert "一镜到底、连续平稳运镜、完整双人对话口播" in autodl
    assert "首尾帧只加强端点约束" in autodl


def test_new_videos_use_fixed_first_last_frames_and_native_dialogue():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    startup = (SKILL_ROOT / "references" / "startup-checklist.md").read_text(encoding="utf-8")
    workflow = (SKILL_ROOT / "references" / "workflow.md").read_text(encoding="utf-8")
    autodl = (SKILL_ROOT / "references" / "autodl-h3.md").read_text(encoding="utf-8")

    assert "所有新视频固定使用 `minimax_h3_lightx2v`" in skill
    assert "行驶双人对话合理尾帧模式：固定启用" in startup
    assert "生成原生双角色对话" in workflow
    assert "模型原生双角色对话音轨" in autodl
    assert "minimax_h3_image_audio_to_video_v2_15s" not in skill


def test_dialogue_scripts_require_distinct_speakers_without_user_listening_gate():
    workflow = (SKILL_ROOT / "references" / "workflow.md").read_text(encoding="utf-8")
    contract = (SKILL_ROOT / "references" / "content-contract.md").read_text(encoding="utf-8")
    review = (SKILL_ROOT / "references" / "review-learning.md").read_text(encoding="utf-8")
    wheelchair = (SKILL_ROOT / "references" / "ayh-wheelchair-rules.md").read_text(encoding="utf-8")

    assert "每条脚本必须恰好包含" in workflow
    assert "两个不同的 `speaker_id`" in workflow
    assert "成片必须逐句核验" in workflow
    assert "必须恰好是两个一致且不同的 ID" in contract
    assert "老人自问自答" in review
    assert "角色身份不得固定为女儿" in wheelchair


def test_every_video_requires_reasonable_4k_tail_first_last_workflow():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    workflow = (SKILL_ROOT / "references" / "workflow.md").read_text(encoding="utf-8")
    autodl = (SKILL_ROOT / "references" / "autodl-h3.md").read_text(encoding="utf-8")

    assert "每条项目固定为轮椅真实向前行驶" in skill
    assert "所有新视频固定使用 `minimax_h3_lightx2v`" in skill
    assert "2160×3840" in workflow
    assert "约 1–1.5 米" in workflow
    assert "尾帧不得复用首帧" in autodl
    assert "first_frame" in autodl and "last_frame" in autodl


def test_dialogue_roles_are_relationship_agnostic_and_end_with_order_cta():
    contract = (SKILL_ROOT / "references" / "content-contract.md").read_text(encoding="utf-8")
    wheelchair = (SKILL_ROOT / "references" / "ayh-wheelchair-rules.md").read_text(encoding="utf-8")

    assert "陪护者/家属" in contract
    assert "儿子、女儿、孙子、孙女" in contract
    assert "提问者提出问题" in contract
    assert "老人回答卖点" in contract
    assert "下单类行动指令" in contract
    assert "角色身份不得固定为女儿" in wheelchair
    assert "自然看向对方" in wheelchair
    assert "老人自问自答" in wheelchair


def test_reasonable_tail_review_keeps_hard_failures_and_user_final_decision():
    review = (SKILL_ROOT / "references" / "review-learning.md").read_text(encoding="utf-8")

    assert "自然视角变化" in review
    assert "轻微亮度波动" in review
    assert "不得单独自动判为硬失败" in review
    assert "切镜、人物裁切、产品结构变形" in review
    assert "用户明确验收结论为最终状态" in review
    assert "保留自动检查证据" in review


def test_review_report_contains_one_card_per_video(tmp_path):
    runtime = load_script("workflow_cli.py")
    batch = tmp_path / "20260826_批次001"
    for video_id in ("V001", "V002"):
        item = batch / f"{video_id}_卖点_封面"
        item.mkdir(parents=True)
        (item / "标题.txt").write_text(f"{video_id} 电动轮椅标题\n封面标题：出门方便", encoding="utf-8")
        if video_id == "V001":
            state = item / "_工作文件" / "任务状态" / "任务信息.json"
            qa = item / "_工作文件" / "验收记录" / "自动验收报告.md"
            state.parent.mkdir(parents=True)
            qa.parent.mkdir(parents=True)
        else:
            state = item / "任务信息.json"
            qa = item / "自动验收报告.md"
        state.write_text(json.dumps({"video_id": video_id, "task_id": f"task-{video_id}"}), encoding="utf-8")
        qa.write_text(f"{video_id} 自动检查通过", encoding="utf-8")
        (item / "视频.mp4").write_bytes(b"mp4")
    report = runtime.build_review_report(batch)
    html = report.read_text(encoding="utf-8")
    assert report.name == "批次验收报告.html"
    assert html.count('class="video-card"') == 2
    assert "task-V001" in html and "task-V002" in html
    assert "V001 自动检查通过" in html and "V002 自动检查通过" in html
    assert "不通过原因" in html
    assert "完成验收" in html


def test_review_report_shows_candidate_video_without_treating_unapproved_root_as_valid(tmp_path):
    runtime = load_script("workflow_cli.py")
    batch = tmp_path / "20260828_批次001"
    item = batch / "V001_卖点_待生成"
    candidate = item / "_工作文件" / "生成过程" / "候选视频.mp4"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"candidate-video")
    (item / "视频.mp4").write_bytes(b"unapproved-video")

    unapproved_html = runtime.build_review_report(batch).read_text(encoding="utf-8")
    assert "<video controls" in unapproved_html
    assert "待明确验收" in unapproved_html
    assert runtime._sha256_file(candidate) in unapproved_html
    assert "_工作文件/生成过程/候选视频.mp4" in unapproved_html
    assert "unapproved-video" not in unapproved_html

    event = runtime.record_artifact_decision(item, "视频.mp4", candidate, "passed", "用户", "视频明确通过")
    runtime.promote_approved_artifact(item, event)
    approved_html = runtime.build_review_report(batch).read_text(encoding="utf-8")
    assert "<video controls" in approved_html


def test_record_review_writes_item_evidence_to_work_dir(tmp_path):
    runtime = load_script("workflow_cli.py")
    batch = tmp_path / "20260826_批次001"
    item = batch / "V001_卖点_封面"
    item.mkdir(parents=True)
    result = tmp_path / "result.json"
    result.write_text(
        json.dumps({"items": [{"video_id": "V001", "decision": "passed", "reason": "", "suggestion": ""}]}),
        encoding="utf-8",
    )

    runtime.record_review(batch, result, tmp_path / "knowledge")

    assert (item / "_工作文件" / "验收记录" / "人工验收结果.md").exists()
    assert not (item / "人工验收结果.md").exists()


def test_failed_learning_review_writes_structured_candidate_experience(tmp_path):
    runtime = load_script("workflow_cli.py")
    batch = tmp_path / "20260829_批次001"
    item = batch / "V001_卖点_封面"
    item.mkdir(parents=True)
    runtime.atomic_write_json(
        batch / "启动确认单.json",
        {"run_mode": "learning", "product_name": "产品甲"},
    )
    result = tmp_path / "result.json"
    runtime.atomic_write_json(
        result,
        {
            "items": [
                {
                    "video_id": "V001",
                    "decision": "failed",
                    "reason": "轮椅扶手结构错误",
                    "suggestion": "锁定左右扶手结构",
                    "node": "storyboard",
                }
            ]
        },
    )

    runtime.record_review(batch, result, tmp_path / "knowledge")

    candidates = list((tmp_path / "knowledge" / "候选经验").glob("*.json"))
    assert len(candidates) == 1
    candidate = json.loads(candidates[0].read_text(encoding="utf-8"))
    assert candidate["status"] == "candidate"
    assert candidate["user_feedback"] == "轮椅扶手结构错误"
    assert candidate["root_cause"] == "未知，待 V02 验证"
    assert candidate["prevention_rule"] == "锁定左右扶手结构"
    assert candidate["validation"]["result"] == "pending"


def test_capture_learning_issue_preserves_feedback_and_structured_review(tmp_path):
    runtime = load_script("workflow_cli.py")
    batch = tmp_path / "20260829_批次001"
    batch.mkdir()
    (batch / "启动确认单.json").write_text(
        json.dumps(
            {
                "run_mode": "learning",
                "product_name": "轻便侠",
                "product_dir": str(tmp_path / "轻便侠"),
            }
        ),
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(b"candidate")

    path = runtime.capture_learning_issue(
        knowledge_dir=tmp_path / "knowledge",
        batch_dir=batch,
        video_id="V001",
        node="storyboard",
        user_feedback="轮椅扶手结构画错了",
        symptom="右侧扶手缺失",
        root_cause="参考图约束没有写入保持项",
        solution="在提示词保持项中锁定左右扶手",
        prevention_rule="提交生图前检查保持项包含左右扶手",
        validation_method="V02 左右扶手均存在且用户通过",
        validation_expected="左右扶手结构与主参考图一致",
        evidence_paths=(candidate,),
        model="Codex ImageGen",
        channel="本机 Codex 界面",
    )

    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["status"] == "candidate"
    assert value["user_feedback"] == "轮椅扶手结构画错了"
    assert value["validation"]["result"] == "pending"
    assert value["evidence"][0]["sha256"] == runtime._sha256_file(candidate)


def test_capture_learning_issue_rejects_auto_mode(tmp_path):
    runtime = load_script("workflow_cli.py")
    batch = tmp_path / "batch"
    batch.mkdir()
    (batch / "启动确认单.json").write_text(
        json.dumps({"run_mode": "auto", "product_name": "轻便侠"}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="学习模式"):
        runtime.capture_learning_issue(
            knowledge_dir=tmp_path / "knowledge",
            batch_dir=batch,
            video_id="V001",
            node="video",
            user_feedback="问题",
            symptom="表现",
            root_cause="未知，待验证",
            solution="方案",
            prevention_rule="规则",
            validation_method="方法",
            validation_expected="结果",
        )


def test_capture_learning_issue_deduplicates_concurrent_feedback(tmp_path):
    runtime = load_script("workflow_cli.py")
    batch = tmp_path / "batch"
    batch.mkdir()
    runtime.atomic_write_json(
        batch / "启动确认单.json",
        {"run_mode": "learning", "product_name": "轻便侠"},
    )

    def capture(_):
        return runtime.capture_learning_issue(
            knowledge_dir=tmp_path / "knowledge",
            batch_dir=batch,
            video_id="V001",
            node="video",
            user_feedback="尾句被截断",
            symptom="结尾不完整",
            root_cause="口播超时",
            solution="缩短口播",
            prevention_rule="提交前检查口播长度",
            validation_method="核对 V02 转写",
            validation_expected="尾句完整",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(capture, range(12)))

    value = json.loads(paths[0].read_text(encoding="utf-8"))
    assert len(set(paths)) == 1
    assert len(value["duplicate_events"]) == 11


def _learning_validation_fixture(runtime, tmp_path, issue_id="issue_a", prevention_rule="提交前检查口播在14秒内结束"):
    knowledge = tmp_path / "knowledge"
    batch = tmp_path / "batch"
    batch.mkdir(parents=True, exist_ok=True)
    (batch / "启动确认单.json").write_text(
        json.dumps({"run_mode": "learning"}), encoding="utf-8"
    )
    item = batch / "V001_卖点_待生成"
    runtime.ensure_work_dirs(item)
    runtime.atomic_write_json(
        runtime.work_path(item, "任务状态", "任务信息.json"),
        {"video_id": "V001", "retry_count": 1},
    )
    approved = runtime.work_path(item, "生成过程", f"{issue_id}.mp4")
    approved.write_bytes(f"verified-{issue_id}".encode())
    issue = knowledge / "候选经验" / f"{issue_id}.json"
    runtime.atomic_write_json(
        issue,
        {
            "issue_id": issue_id,
            "status": "candidate",
            "scope": {
                "product_id": "p1",
                "node": "video",
                "model": "H3",
                "channel": "AutoDL",
            },
            "user_feedback": "尾句被截断",
            "symptom": "结尾听不完整",
            "root_cause": "口播超时",
            "solution": "缩短口播",
            "prevention_rule": prevention_rule,
            "validation": {
                "method": "V02转写完整",
                "expected": "尾句完整",
                "result": "pending",
            },
            "source_batch": str(batch.resolve()),
            "source_video_id": "V001",
            "created_at": "2026-08-29T00:00:00+08:00",
        },
    )
    return knowledge, batch, approved, issue


def test_validate_learning_issue_promotes_only_verified_v02(tmp_path):
    runtime = load_script("workflow_cli.py")
    knowledge, batch, approved, issue = _learning_validation_fixture(runtime, tmp_path)

    rule_path = runtime.validate_learning_issue(
        knowledge_dir=knowledge,
        batch_dir=batch,
        video_id="V001",
        issue_id="issue_a",
        result="passed",
        verified_candidate=approved,
    )

    rule = json.loads(rule_path.read_text(encoding="utf-8"))
    assert rule["status"] == "active"
    assert rule["required_action"] == "提交前检查口播在14秒内结束"
    assert rule["verified_candidate_sha256"] == runtime._sha256_file(approved)
    assert json.loads(issue.read_text(encoding="utf-8"))["status"] == "promoted"


@pytest.mark.parametrize("result", ["failed", "inconclusive"])
def test_validate_learning_issue_does_not_promote_unverified_results(tmp_path, result):
    runtime = load_script("workflow_cli.py")
    knowledge, batch, _, issue = _learning_validation_fixture(runtime, tmp_path)

    promoted = runtime.validate_learning_issue(
        knowledge_dir=knowledge,
        batch_dir=batch,
        video_id="V001",
        issue_id="issue_a",
        result=result,
        verified_candidate=None,
    )

    assert promoted is None
    assert not list((knowledge / "正式规则").glob("*.json"))
    value = json.loads(issue.read_text(encoding="utf-8"))
    assert value["status"] == result
    assert value["validation"]["result"] == result


def test_new_verified_rule_supersedes_conflicting_scope(tmp_path):
    runtime = load_script("workflow_cli.py")
    knowledge, batch, first_candidate, _ = _learning_validation_fixture(
        runtime, tmp_path, issue_id="issue_first", prevention_rule="动作一"
    )
    first_path = runtime.validate_learning_issue(
        knowledge_dir=knowledge,
        batch_dir=batch,
        video_id="V001",
        issue_id="issue_first",
        result="passed",
        verified_candidate=first_candidate,
    )
    _, _, second_candidate, _ = _learning_validation_fixture(
        runtime, tmp_path, issue_id="issue_second", prevention_rule="动作二"
    )

    second_path = runtime.validate_learning_issue(
        knowledge_dir=knowledge,
        batch_dir=batch,
        video_id="V001",
        issue_id="issue_second",
        result="passed",
        verified_candidate=second_candidate,
    )

    first = json.loads(first_path.read_text(encoding="utf-8"))
    second = json.loads(second_path.read_text(encoding="utf-8"))
    assert first["status"] == "superseded"
    assert first["superseded_by"] == second["rule_id"]
    assert second["status"] == "active"
    assert second["version"] == 2


def test_concurrent_learning_promotions_keep_one_active_rule(tmp_path):
    runtime = load_script("workflow_cli.py")
    prepared = []
    for index in range(12):
        issue_id = f"issue_{index:02d}"
        knowledge, batch, candidate, _ = _learning_validation_fixture(
            runtime, tmp_path, issue_id=issue_id, prevention_rule=f"动作{index:02d}"
        )
        prepared.append((issue_id, candidate))

    def promote(values):
        issue_id, candidate = values
        return runtime.validate_learning_issue(
            knowledge_dir=knowledge,
            batch_dir=batch,
            video_id="V001",
            issue_id=issue_id,
            result="passed",
            verified_candidate=candidate,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(promote, prepared))

    rules = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (knowledge / "正式规则").glob("*.json")
    ]
    assert sum(rule["status"] == "active" for rule in rules) == 1
    assert {rule["version"] for rule in rules} == set(range(1, 13))


def _write_learning_rule(runtime, rules_dir, rule_id, scope, action, verified_at):
    runtime.atomic_write_json(
        rules_dir / f"{rule_id}.json",
        {
            "rule_id": rule_id,
            "version": 1,
            "status": "active",
            "scope": scope,
            "trigger": "测试触发条件",
            "required_action": action,
            "validation_check": "测试检查",
            "verified_at": verified_at,
            "hit_count": 0,
            "last_hit_at": None,
        },
    )


def test_load_matching_rules_prefers_product_and_precise_scope(tmp_path):
    runtime = load_script("workflow_cli.py")
    rules = tmp_path / "正式规则"
    _write_learning_rule(
        runtime,
        rules,
        "global",
        {"product_id": None, "node": "video", "model": None, "channel": None},
        "全局动作",
        "2026-08-28T00:00:00+08:00",
    )
    _write_learning_rule(
        runtime,
        rules,
        "product",
        {"product_id": "p1", "node": "video", "model": "H3", "channel": "AutoDL"},
        "产品动作",
        "2026-08-29T00:00:00+08:00",
    )

    matched = runtime.load_matching_rules(
        tmp_path, product_id="p1", node="video", model="H3", channel="AutoDL"
    )

    assert [rule["rule_id"] for rule in matched] == ["product", "global"]


def test_initialize_batch_records_matching_formal_rules(tmp_path):
    runtime = load_script("workflow_cli.py")
    product = tmp_path / "产品甲"
    product.mkdir()
    Image.new("RGB", (64, 64), "white").save(product / "产品.png")
    covers = tmp_path / "封面参考"
    covers.mkdir()
    Image.new("RGB", (64, 64), "navy").save(covers / "参考.png")
    knowledge = tmp_path / "knowledge"
    product_id = runtime._product_id("产品甲")
    _write_learning_rule(
        runtime,
        knowledge / "正式规则",
        "product-rule",
        {"product_id": product_id, "node": "storyboard", "model": None, "channel": None},
        "提交前锁定产品结构",
        "2026-08-29T00:00:00+08:00",
    )

    context = runtime.initialize_batch(
        product_dir=product,
        product_name="产品甲",
        selling_points=("轻便",),
        total_videos=1,
        run_mode="learning",
        resolution="768P",
        max_budget_yuan="20",
        cover_reference_dir=covers,
        knowledge_dir=knowledge,
        now=datetime(2026, 8, 29, 12, 0, 0),
    )

    confirmation = json.loads((context.batch_dir / "启动确认单.json").read_text(encoding="utf-8"))
    assert confirmation["formal_rules_library"] == str((knowledge / "正式规则").resolve())
    assert confirmation["matched_learning_rules"][0]["rule_id"] == "product-rule"


def test_prepare_node_rules_records_hits_without_lost_updates(tmp_path):
    runtime = load_script("workflow_cli.py")
    knowledge = tmp_path / "knowledge"
    _write_learning_rule(
        runtime,
        knowledge / "正式规则",
        "rule-hit",
        {"product_id": "p1", "node": "video", "model": "H3", "channel": "AutoDL"},
        "提交前检查完整口播",
        "2026-08-29T00:00:00+08:00",
    )
    batch = tmp_path / "batch"
    batch.mkdir()
    runtime.atomic_write_json(
        batch / "启动确认单.json",
        {"product_name": "产品甲", "product_id": "p1", "run_mode": "learning"},
    )
    item = batch / "V001_卖点_待生成"
    runtime.ensure_work_dirs(item)

    def prepare(_):
        return runtime.prepare_node_rules(
            knowledge_dir=knowledge,
            batch_dir=batch,
            video_id="V001",
            node="video",
            model="H3",
            channel="AutoDL",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(prepare, range(12)))

    manifest = json.loads(paths[0].read_text(encoding="utf-8"))
    rule = json.loads((knowledge / "正式规则" / "rule-hit.json").read_text(encoding="utf-8"))
    assert manifest["rules"][0]["required_action"] == "提交前检查完整口播"
    assert rule["hit_count"] == 12
    assert rule["last_hit_at"]


def test_learning_cli_commands_are_exposed():
    environment = dict(os.environ, PYTHONUTF8="1")
    result = subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts" / "workflow_cli.py"), "--help"],
        capture_output=True,
        env=environment,
    )
    assert result.returncode == 0
    stdout = result.stdout.decode(errors="replace")
    assert "record-issue" in stdout
    assert "validate-learning" in stdout
    assert "prepare-node-rules" in stdout
    assert "start-rerun" in stdout


def test_record_issue_cli_writes_candidate(tmp_path):
    batch = tmp_path / "batch"
    batch.mkdir()
    (batch / "启动确认单.json").write_text(
        json.dumps({"run_mode": "learning", "product_name": "产品甲"}), encoding="utf-8"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "workflow_cli.py"),
            "record-issue",
            "--knowledge-dir",
            str(tmp_path / "knowledge"),
            "--batch",
            str(batch),
            "--video-id",
            "V001",
            "--node",
            "video",
            "--feedback",
            "尾句截断",
            "--symptom",
            "结尾不完整",
            "--root-cause",
            "口播超时",
            "--solution",
            "缩短口播",
            "--prevention-rule",
            "提交前检查口播长度",
            "--validation-method",
            "核对V02转写",
            "--validation-expected",
            "尾句完整",
        ],
        capture_output=True,
        env=dict(os.environ, PYTHONUTF8="1"),
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    output = Path(result.stdout.decode("utf-8").strip())
    assert output.is_file()
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "candidate"


def test_start_rerun_allows_only_v02_and_updates_batch_table(tmp_path):
    runtime = load_script("workflow_cli.py")
    batch = tmp_path / "batch"
    batch.mkdir()
    item = batch / "V001_卖点_待生成"
    runtime.ensure_work_dirs(item)
    task = {"video_id": "V001", "retry_count": 0, "status": "REVIEW_FAILED"}
    runtime.atomic_write_json(runtime.work_path(item, "任务状态", "任务信息.json"), task)
    runtime.atomic_write_json(batch / "批次任务表.json", {"items": [task]})

    task_path = runtime.start_rerun(batch, "V001")

    updated = json.loads(task_path.read_text(encoding="utf-8"))
    table = json.loads((batch / "批次任务表.json").read_text(encoding="utf-8"))
    assert updated["retry_count"] == 1
    assert updated["status"] == "V02_READY"
    assert table["items"][0]["retry_count"] == 1
    assert runtime.work_path(item, "历史版本", "视频版本/V02_唯一一次重跑").is_dir()
    with pytest.raises(ValueError, match="V02"):
        runtime.start_rerun(batch, "V001")


def test_self_test_is_windows_encoding_safe():
    environment = dict(os.environ)
    environment.pop("PYTHONUTF8", None)
    result = subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts" / "self_test.py")],
        cwd=SKILL_ROOT,
        env=environment,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_self_test_covers_learning_resources_and_commands():
    text = (SKILL_ROOT / "scripts" / "self_test.py").read_text(encoding="utf-8")
    assert "references/automatic-learning-rules.md" in text
    assert "references/image-generation-routing.md" in text
    assert "record-issue" in text
    assert "validate-learning" in text
    assert "prepare-node-rules" in text
    assert "start-rerun" in text


def test_cover_cli_accepts_utf8_title_file(tmp_path):
    storyboard = tmp_path / "分镜图.png"
    reference = tmp_path / "参考图.png"
    title_file = tmp_path / "封面标题.txt"
    output = tmp_path / "封面图.png"
    Image.new("RGB", (768, 1365), "white").save(storyboard)
    Image.new("RGB", (768, 1365), "navy").save(reference)
    title_file.write_text("爸妈会操作\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "render_cover.py"),
            "--storyboard",
            str(storyboard),
            "--title-file",
            str(title_file),
            "--reference",
            str(reference),
            "--output",
            str(output),
        ],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    image = Image.open(output)
    assert image.text["cover_title"] == "爸妈会操作"
