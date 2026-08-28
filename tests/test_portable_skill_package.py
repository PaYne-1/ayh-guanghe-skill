import importlib.util
import json
import os
import subprocess
import sys
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
    deliverables = {"视频.mp4", "封面图.png", "发布正文.md", "标题.txt", "分镜图.png"}
    for name in deliverables:
        (item / name).write_bytes(name.encode("utf-8"))
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
    assert {path.name for path in item.iterdir()} == deliverables | {"_工作文件"}
    assert (item / "_工作文件" / "任务状态" / "任务信息.json").exists()
    assert (item / "_工作文件" / "任务状态" / "查询结果.json").exists()
    assert (item / "_工作文件" / "生成过程" / "视频提示词.txt").exists()
    assert (item / "_工作文件" / "验收记录" / "自动验收报告.md").exists()
    assert (item / "_工作文件" / "历史版本" / "视频_V02.mp4").exists()
    assert (item / "_工作文件" / "历史版本" / "失败版本" / "失败.mp4").exists()
    assert (item / "_工作文件" / "历史版本" / "视频版本" / "V01.mp4").exists()

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
        "video_prompt": "一镜到底，固定镜头，轮椅沿直线缓慢前进，不要背景音乐。",
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
        "video_prompt": "一镜到底，固定镜头，轮椅沿直线缓慢前进。",
        "publish_body": "以前老人总担心操作复杂，家里人每次都要陪在旁边。用了爱优护电动轮椅后，老人自己很快就能上手，平时在小区出门顺手多了，家属照顾也省心。有同样出门需求的家庭，可以了解一下爱优护电动轮椅。",
        "hashtags": ["#爱优护电动轮椅", "#ainsnbot高端智能电动轮椅", "#电动轮椅", "#老人专用电动轮椅"],
    }
    package_path = tmp_path / "content.json"
    package_path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
    profile = SKILL_ROOT / "profiles" / "爱优护电动轮椅_淘宝天猫光合.json"

    runtime.save_content_package(item, package_path, profile)

    assert (item / "标题.txt").exists()
    assert (item / "发布正文.md").exists()
    assert (item / "_工作文件" / "生成过程" / "策划内容.json").exists()
    assert (item / "_工作文件" / "生成过程" / "分镜提示词.txt").exists()
    assert (item / "_工作文件" / "生成过程" / "视频提示词.txt").exists()
    assert not (item / "策划内容.json").exists()


def test_autodl_client_dry_run_is_non_billable_and_task_id_parser_is_tolerant(tmp_path):
    client = load_script("autodl_h3.py")
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "prompt": "固定镜头",
                "duration": 15,
                "resolution": "768p竖",
                "ref_image_0": "data:image/png;base64,AAAA",
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
    assert preview["payload"]["ref_image_0"].startswith("data:image/png;base64,")
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
                "prompt": "固定镜头，首尾画面一致",
                "duration": 15,
                "resolution": "768p竖",
                "first_frame": "data:image/png;base64,AAAA",
                "last_frame": "data:image/png;base64,AAAA",
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
    assert preview["payload"]["first_frame"] == preview["payload"]["last_frame"]


def test_autodl_client_can_preview_multi_image_audio_workflow(tmp_path):
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

    preview = client.submit_payload(
        payload_path,
        api_key="secret",
        dry_run=True,
        workflow_id="minimax_h3_image_audio_to_video_v2_15s",
    )

    assert preview["url"].endswith("/minimax_h3_image_audio_to_video_v2_15s")
    assert preview["payload"]["ref_audio_0"].startswith("data:audio/wav;base64,")


def test_autodl_reference_uses_current_comfyui_workflow():
    text = (SKILL_ROOT / "references" / "autodl-h3.md").read_text(encoding="utf-8")
    assert "minimax_h3_lightx2v_v5_15s" in text
    assert "minimax_h3_lightx2v" in text
    assert "/api/v1/minimax/v2/video_generation" not in text
    assert "ref_image_0" in text
    assert "first_frame" in text
    assert "last_frame" in text
    assert "minimax_h3_image_audio_to_video_v2_15s" in text
    assert "ref_audio_0" in text


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
    assert "完整说完全部口播" in wheelchair


def test_first_last_frame_workflow_applies_core_rules_for_full_duration():
    workflow = (SKILL_ROOT / "references" / "workflow.md").read_text(encoding="utf-8")
    autodl = (SKILL_ROOT / "references" / "autodl-h3.md").read_text(encoding="utf-8")

    assert "整个0–15秒" in workflow
    assert "整个0–15秒" in autodl
    assert "一镜到底、连续平稳运镜、完整口播" in autodl
    assert "不得只约束首帧和尾帧" in autodl


def test_new_videos_generate_and_validate_audio_before_video():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    startup = (SKILL_ROOT / "references" / "startup-checklist.md").read_text(encoding="utf-8")
    workflow = (SKILL_ROOT / "references" / "workflow.md").read_text(encoding="utf-8")
    autodl = (SKILL_ROOT / "references" / "autodl-h3.md").read_text(encoding="utf-8")

    assert "先生成独立口播音轨" in skill
    assert "音轨生成费用" in startup
    assert "14秒内" in workflow
    assert "新视频不得依赖上一版音轨" in autodl
    assert "minimax_h3_image_audio_to_video_v2_15s" in skill


def test_dialogue_scripts_require_distinct_speakers_without_user_listening_gate():
    workflow = (SKILL_ROOT / "references" / "workflow.md").read_text(encoding="utf-8")
    contract = (SKILL_ROOT / "references" / "content-contract.md").read_text(encoding="utf-8")
    review = (SKILL_ROOT / "references" / "review-learning.md").read_text(encoding="utf-8")
    wheelchair = (SKILL_ROOT / "references" / "ayh-wheelchair-rules.md").read_text(encoding="utf-8")

    assert "对话式脚本" in workflow
    assert "每个不同 `speaker_id` 必须使用可区分的独立人物音色" in workflow
    assert "系统自动验收，不设置用户试听确认节点" in workflow
    assert "两个或以上不同的 `speaker_id`" in contract
    assert "老人自问自答" in review
    assert "角色身份不得固定为女儿" in wheelchair


def test_driving_dialogue_prefers_reasonable_4k_tail_first_last_workflow():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    workflow = (SKILL_ROOT / "references" / "workflow.md").read_text(encoding="utf-8")
    autodl = (SKILL_ROOT / "references" / "autodl-h3.md").read_text(encoding="utf-8")

    assert "行驶双人对话场景" in skill
    assert "优先使用 `minimax_h3_lightx2v`" in skill
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
