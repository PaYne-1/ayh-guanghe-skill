import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

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


def test_autodl_client_dry_run_is_non_billable_and_task_id_parser_is_tolerant(tmp_path):
    client = load_script("autodl_h3.py")
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps({"prompt": "固定镜头"}, ensure_ascii=False), encoding="utf-8")
    preview = client.submit_payload(payload_path, api_key="secret", dry_run=True)
    assert preview["dry_run"] is True
    assert preview["url"] == "https://www.autodl.art/api/v1/minimax/v2/video_generation"
    assert preview["payload"]["aigc_watermark"] is False
    assert "secret" not in json.dumps(preview, ensure_ascii=False)
    assert client.extract_task_id({"task_id": "root-task"}) == "root-task"
    assert client.extract_task_id({"data": {"task_id": "nested-task"}}) == "nested-task"


def test_review_report_contains_one_card_per_video(tmp_path):
    runtime = load_script("workflow_cli.py")
    batch = tmp_path / "20260826_批次001"
    for video_id in ("V001", "V002"):
        item = batch / f"{video_id}_卖点_封面"
        item.mkdir(parents=True)
        (item / "标题.txt").write_text(f"{video_id} 电动轮椅标题\n封面标题：出门方便", encoding="utf-8")
        (item / "任务信息.json").write_text(json.dumps({"video_id": video_id, "task_id": f"task-{video_id}"}), encoding="utf-8")
        (item / "自动验收报告.md").write_text("自动检查通过", encoding="utf-8")
        (item / "视频.mp4").write_bytes(b"mp4")
    report = runtime.build_review_report(batch)
    html = report.read_text(encoding="utf-8")
    assert report.name == "批次验收报告.html"
    assert html.count('class="video-card"') == 2
    assert "不通过原因" in html
    assert "完成验收" in html


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
