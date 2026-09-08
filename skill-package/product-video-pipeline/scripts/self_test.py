#!/usr/bin/env python3
"""No-network, no-charge self-test for the portable skill package."""

from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    required = (
        "SKILL.md",
        "profiles/爱优护电动轮椅_淘宝天猫光合.json",
        "references/workflow.md",
        "references/startup-checklist.md",
        "references/content-contract.md",
        "references/ayh-wheelchair-rules.md",
        "references/autodl-h3.md",
        "references/review-learning.md",
        "references/automatic-learning-rules.md",
        "references/image-generation-routing.md",
        "references/install.md",
        "pipeline_policy.json",
        "scripts/pipeline_policy.py",
        "scripts/pipeline_runner.py",
        "scripts/workflow_cli.py",
        "scripts/autodl_h3.py",
        "scripts/render_cover.py",
    )
    missing = [path for path in required if not (SKILL_ROOT / path).exists()]
    if missing:
        print("缺少文件：" + ", ".join(missing), file=sys.stderr)
        return 1
    child_environment = dict(os.environ)
    child_environment["PYTHONUTF8"] = "1"
    workflow_script = SKILL_ROOT / "scripts" / "workflow_cli.py"
    workflow_help = subprocess.run(
        [sys.executable, str(workflow_script), "--help"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=child_environment,
    ).stdout
    for command in ("record-issue", "validate-learning", "prepare-node-rules", "start-rerun"):
        assert command in workflow_help
    runner_help = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "pipeline_runner.py"),
            "--help",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=child_environment,
    ).stdout
    for command in (
        "status",
        "approve-start",
        "next",
        "accept-content",
        "accept-image",
        "image-failed",
        "run-local",
        "approve-rerun",
        "complete-review",
    ):
        assert command in runner_help
    with tempfile.TemporaryDirectory() as temporary:
        temporary_root = Path(temporary)
        batch = temporary_root / "batch"
        item = batch / "V001_point_pending"
        state_dir = item / "_工作文件" / "任务状态"
        state_dir.mkdir(parents=True)
        (batch / "启动确认单.json").write_text(
            json.dumps({"run_mode": "learning", "product_name": "self-test", "product_id": "self-test"}),
            encoding="utf-8",
        )
        (state_dir / "任务信息.json").write_text(
            json.dumps({"video_id": "V001", "retry_count": 0}), encoding="utf-8"
        )
        knowledge = temporary_root / "knowledge"
        issue_result = subprocess.run(
            [
                sys.executable,
                str(workflow_script),
                "record-issue",
                "--knowledge-dir",
                str(knowledge),
                "--batch",
                str(batch),
                "--video-id",
                "V001",
                "--node",
                "video",
                "--feedback",
                "ending truncated",
                "--symptom",
                "ending incomplete",
                "--root-cause",
                "audio too long",
                "--solution",
                "shorten audio",
                "--prevention-rule",
                "check audio duration",
                "--validation-method",
                "review V02 transcript",
                "--validation-expected",
                "ending complete",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=child_environment,
        )
        issue_id = json.loads(Path(issue_result.stdout.strip()).read_text(encoding="utf-8"))["issue_id"]
        subprocess.run(
            [
                sys.executable,
                str(workflow_script),
                "start-rerun",
                "--batch",
                str(batch),
                "--video-id",
                "V001",
            ],
            check=True,
            capture_output=True,
            env=child_environment,
        )
        subprocess.run(
            [
                sys.executable,
                str(workflow_script),
                "validate-learning",
                "--knowledge-dir",
                str(knowledge),
                "--batch",
                str(batch),
                "--video-id",
                "V001",
                "--issue-id",
                issue_id,
                "--result",
                "failed",
            ],
            check=True,
            capture_output=True,
            env=child_environment,
        )
        node_result = subprocess.run(
            [
                sys.executable,
                str(workflow_script),
                "prepare-node-rules",
                "--knowledge-dir",
                str(knowledge),
                "--batch",
                str(batch),
                "--video-id",
                "V001",
                "--node",
                "video",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=child_environment,
        )
        assert json.loads(Path(node_result.stdout.strip()).read_text(encoding="utf-8"))["rules"] == []
        payload = Path(temporary) / "payload.json"
        payload.write_text(
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
        result = subprocess.run(
            [sys.executable, str(SKILL_ROOT / "scripts" / "autodl_h3.py"), "submit", "--payload", str(payload), "--dry-run"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=child_environment,
        )
        preview = json.loads(result.stdout)
        assert preview["dry_run"] is True
        assert preview["url"].endswith("/minimax_h3_lightx2v_v5_15s")
        assert preview["payload"]["resolution"] == "768p竖"
        assert "aigc_watermark" not in preview["payload"]
        legacy_payload = Path(temporary) / "legacy-payload.json"
        legacy_payload.write_text(
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
        rejected = subprocess.run(
            [
                sys.executable,
                str(SKILL_ROOT / "scripts" / "autodl_h3.py"),
                "submit",
                "--payload",
                str(legacy_payload),
                "--dry-run",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=child_environment,
        )
        assert rejected.returncode == 2
        assert "first_frame" in rejected.stderr
        assert "last_frame" in rejected.stderr
    workflow_spec = importlib.util.spec_from_file_location("workflow_cli", workflow_script)
    assert workflow_spec and workflow_spec.loader
    workflow_module = importlib.util.module_from_spec(workflow_spec)
    workflow_spec.loader.exec_module(workflow_module)
    assert workflow_module.DELIVERABLE_NAMES == {
        "视频.mp4",
        "封面图.png",
        "发布正文.txt",
        "话题标签.txt",
        "标题.txt",
        "分镜图.png",
        "尾帧图.png",
    }
    with tempfile.TemporaryDirectory() as delivery_temporary:
        item_dir = Path(delivery_temporary) / "V001_point_pending"
        process_dir = item_dir / "_工作文件" / "生成过程"
        process_dir.mkdir(parents=True)
        title_candidate = process_dir / "标题.txt"
        title_candidate.write_text(
            "发布标题：菜市场湿滑路面，走得稳\n封面标题：湿地稳稳走\n",
            encoding="utf-8",
        )
        title_event = workflow_module.record_artifact_decision(
            item_dir,
            "标题.txt",
            title_candidate,
            "passed",
            "self-test",
            "title approved",
        )
        workflow_module.promote_approved_artifact(item_dir, title_event)
        video_candidate = process_dir / "视频候选.mp4"
        video_candidate.write_bytes(b"self-test-video")
        video_event = workflow_module.record_artifact_decision(
            item_dir,
            "视频.mp4",
            video_candidate,
            "passed",
            "self-test",
            "video approved",
        )
        promoted_video = workflow_module.promote_approved_artifact(item_dir, video_event)
        assert promoted_video.name == "菜市场湿滑路面 走得稳.mp4"
        assert not (item_dir / "视频.mp4").exists()
        assert workflow_module.validated_promoted_artifact_path(item_dir, "视频.mp4") == promoted_video
        delivery_audit = workflow_module.audit_promoted_outputs(item_dir)
        assert any(row["artifact_name"] == "视频.mp4" for row in delivery_audit["valid"])
    profile = json.loads(
        (SKILL_ROOT / "profiles" / "爱优护电动轮椅_淘宝天猫光合.json").read_text(encoding="utf-8")
    )
    single_person_content = {
        "publish_title": "老人出门代步为什么要选电动轮椅",
        "cover_title": "出门更轻松",
        "people": [
            {
                "id": "P1",
                "identity": "老人",
                "gender": "女",
                "age_feel": "70岁左右",
                "position": "坐在轮椅上",
                "action": "缓慢前行",
                "speaks": True,
            }
        ],
        "storyboard_people": ["P1"],
        "script_segments": [
            {"start": 0, "end": 4, "speaker_id": "P1", "dialogue": "开场"},
            {"start": 4, "end": 11, "speaker_id": "P1", "dialogue": "回答"},
            {"start": 11, "end": 15, "speaker_id": "P1", "dialogue": "用了爱优护电动轮椅后出门更方便，可以选择"},
        ],
        "video_prompt": "一镜到底，连续平稳运镜，完整双人对话口播",
        "publish_body": "这是一段用于验证内容契约的产品介绍正文，描述老人乘坐爱优护电动轮椅直线缓慢前行，与陪护者自然交流操作体验和出行改善。画面保持真实自然，两人始终同框，轮椅结构清楚完整，内容表达克制，不夸大产品效果，也不虚构价格参数，并提醒有需要的家庭结合实际情况认真选择。",
        "hashtags": profile["fixed_hashtags"],
    }
    content_issues = workflow_module.validate_content_package(single_person_content, profile)
    assert "people.exactly_two_required" in content_issues
    assert "script.exactly_two_speakers_required" in content_issues
    assert "content.tail_frame_prompt_missing" in content_issues
    incomplete_prompt_content = dict(single_person_content)
    incomplete_prompt_content["video_prompt"] = "一镜到底，连续平稳运镜"
    assert "shot.full_duration_rules_missing" in workflow_module.validate_content_package(
        incomplete_prompt_content, profile
    )
    valid_content = json.loads(json.dumps(single_person_content, ensure_ascii=False))
    valid_content["people"].append(
        {
            "id": "P2",
            "identity": "家属",
            "gender": "男",
            "age_feel": "40岁左右",
            "position": "轮椅旁",
            "action": "陪同步行",
            "speaks": True,
        }
    )
    valid_content["storyboard_people"] = ["P1", "P2"]
    valid_content["script_segments"][0]["speaker_id"] = "P2"
    valid_content["storyboard_prompt"] = "竖屏4K，2160×3840，9:16，老人和家属陪同直线行驶"
    valid_content["last_frame_prompt"] = "同尺寸合理尾帧，主体继续前进1至1.5米"
    with tempfile.TemporaryDirectory() as content_temporary:
        content_root = Path(content_temporary)
        content_path = content_root / "content.json"
        content_path.write_text(json.dumps(valid_content, ensure_ascii=False), encoding="utf-8")
        workflow_module.save_content_package(
            content_root / "item",
            content_path,
            SKILL_ROOT / "profiles" / "爱优护电动轮椅_淘宝天猫光合.json",
        )
        process = content_root / "item" / "_工作文件" / "生成过程"
        assert (process / "合理尾帧提示词.txt").is_file()
        assert (process / "发布正文.txt").read_text(encoding="utf-8") == valid_content["publish_body"] + "\n"
        assert (process / "话题标签.txt").read_text(encoding="utf-8") == " ".join(valid_content["hashtags"]) + "\n"
    required_phrases = {
        "SKILL.md": (
            "minimax_h3_lightx2v",
            "七项最终产出",
            "尾帧图.png",
            "话题标签.txt",
            "你需要提供的内容",
            "本次配置明细",
            "请你回复",
            "每次任务",
            "第一步",
            "开始产品视频",
            "制作产品视频",
            "生成产品视频",
            "光合视频任务",
            "GPT 一次生成包含准确标题的完整封面",
            "用户明确同意重跑后",
            "首次启动清单不询问 AutoDL API 接入状态或鉴权方式",
            "自动生产模式的启动确认是前置节点持续执行授权",
            "任务只有在七项最终产出审计全部有效后才算完成",
        ),
        "references/workflow.md": (
            "first_frame",
            "last_frame",
            "尾帧图.png",
            "发布正文.txt",
            "用户明确同意重跑后",
        ),
        "references/image-generation-routing.md": ("禁止代码叠字",),
        "references/startup-checklist.md": (
            "固定启用",
            "minimax_h3_lightx2v",
            "你需要提供的内容",
            "本次配置明细",
            "请你回复",
            "每次任务",
            "未收到用户明确回复前",
            "不扫描产品素材",
            "可复制填写",
            "只有明确触发词",
            "只有缺少 `AUTODL_API_KEY`",
            "自动生产模式不再逐节点询问",
        ),
        "references/autodl-h3.md": ("first_frame", "last_frame", "默认新视频工作流 ID：`minimax_h3_lightx2v_v5_15s`"),
        "references/content-contract.md": ("双人对话", "合理尾帧"),
        "references/delivery-contract.md": (
            "Codex 原生生图",
            "批准当前节点后继续",
            "发布标题",
            "特殊标点替换为单个空格",
            "最终文件夹路径",
            "只读取以 `发布标题：` 开头的行",
            "七项最终产出全部有效",
            "能够仅靠等比缩放和留边",
        ),
        "references/review-learning.md": (
            "自动验收只形成证据",
            "用户明确同意重跑后",
            "用户明确通过优先于自动验收结论",
            "追加新的 `passed` 事件",
        ),
    }
    for relative_path, phrases in required_phrases.items():
        content = (SKILL_ROOT / relative_path).read_text(encoding="utf-8")
        for phrase in phrases:
            assert phrase in content, f"{relative_path} 缺少统一首尾帧规则：{phrase}"
    forbidden_phrases = (
        "每个全新的 Codex 任务窗口中，第一条用户消息无论内容是什么",
        "其他场景继续使用已确认的现有工作流",
        "是否命中行驶双人对话合理尾帧模式：是 / 否",
        "合理尾帧首尾帧视频预计费用（命中时）",
        "新视频默认使用 `minimax_h3_image_audio_to_video_v2_15s`",
        "五项最终产出",
        "只有五项固定产出",
        "发布正文.md",
        "不作为第二张一级分镜",
        "不晋升为第二张一级分镜",
        "封面底图不得让生图模型绘制最终中文标题",
        "默认可用程序绘制",
        "第一条用户消息无论内容是什么",
        "新窗口第一条消息为“你好” | 立即发送完整启动清单",
    )
    maintained_documents = ("SKILL.md",) + tuple(
        str(path.relative_to(SKILL_ROOT)).replace("\\", "/")
        for path in (SKILL_ROOT / "references").glob("*.md")
    )
    for relative_path in maintained_documents:
        content = (SKILL_ROOT / relative_path).read_text(encoding="utf-8")
        for phrase in forbidden_phrases:
            assert phrase not in content, f"{relative_path} 仍包含旧条件分支：{phrase}"
    print("product-video-pipeline 自检通过（未联网、未产生费用）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
