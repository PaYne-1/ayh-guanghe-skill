#!/usr/bin/env python3
"""No-network, no-charge self-test for the portable skill package."""

from __future__ import annotations

import json
import io
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from contextlib import redirect_stdout

from PIL import Image


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
        "references/delivery-contract.md",
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
        "request-rerun",
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
        "storyboard_prompt": "原生2160×3840，固定中远景，老人和陪护者与完整产品处于安全区",
        "last_frame_prompt": "原生2160×3840，固定中远景，连续前进后的合理尾帧",
        "video_prompt": "一镜到底，连续平稳运镜，完整双人对话口播",
        "publish_body": "这是一段用于验证内容契约的产品介绍正文，描述老人乘坐爱优护电动轮椅直线缓慢前行，与陪护者自然交流操作体验和出行改善。画面保持真实自然，两人始终同框，轮椅结构清楚完整，内容表达克制，不夸大产品效果，也不虚构价格参数，并提醒有需要的家庭结合实际情况认真选择。",
        "hashtags": profile["fixed_hashtags"],
    }
    content_issues = workflow_module.validate_content_package(single_person_content, profile)
    assert "people.exactly_two_required" in content_issues
    assert "script.exactly_two_speakers_required" in content_issues
    for malformed in ([], "invalid", None, {"storyboard_people": None}, {"hashtags": None}):
        assert workflow_module.validate_content_package(malformed, profile)
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
    valid_content["script_segments"][2]["speaker_id"] = "P2"
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
        "SKILL.md": ("首次回复同时授权 V01", "原生2160×3840", "WAITING_USER_FEEDBACK", "真实存在的绝对路径"),
        "references/startup-checklist.md": ("你需要提供的内容", "本次配置明细", "请你回复", "本批次最高总预算", "首次回复同时授权 V01", "api_key_env"),
        "references/content-contract.md": ("产品参考图是唯一产品依据", "禁止用文字重新描述产品外观", "非当前说话者嘴巴闭合且完全不发声", "清单之外零人声"),
        "references/image-generation-routing.md": ("GPT_WEB_IMAGE_REQUIRED", "THIRD_PARTY_IMAGE_REQUIRED", "原生2160×3840", "禁止本地放大"),
        "references/workflow.md": ("first_frame", "last_frame", "固定中远景", "V01_DELIVERED", "WAITING_USER_FEEDBACK"),
        "references/autodl-h3.md": ("first_frame", "last_frame", "minimax_h3_lightx2v_v5_15s", "清单之外零人声"),
        "references/delivery-contract.md": ("真实存在的绝对路径", "V01 已下载，等待用户反馈", "WAITING_USER_FEEDBACK"),
        "references/review-learning.md": ("自动检查只形成技术证据", "用户反馈后才允许", "V02"),
        "references/ayh-wheelchair-rules.md": ("产品参考图是唯一产品依据", "固定中远景", "不得注入生成提示词"),
    }
    for relative_path, phrases in required_phrases.items():
        content = (SKILL_ROOT / relative_path).read_text(encoding="utf-8")
        for phrase in phrases:
            assert phrase in content, f"{relative_path} 缺少统一首尾帧规则：{phrase}"
    forbidden_phrases = (
        "每个全新的 Codex 任务窗口中，第一条用户消息无论内容是什么",
        "其他场景继续使用已确认的现有工作流",
        "是否命中行驶双人对话合理尾帧模式：是 / 否",
        "图片 API 批次预算",
        "batch_budget_yuan",
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
    maintained_documents = tuple(required_phrases)
    for relative_path in maintained_documents:
        content = (SKILL_ROOT / relative_path).read_text(encoding="utf-8")
        for phrase in forbidden_phrases:
            assert phrase not in content, f"{relative_path} 仍包含旧条件分支：{phrase}"
    runner_spec = importlib.util.spec_from_file_location("pipeline_runner", SKILL_ROOT / "scripts/pipeline_runner.py")
    runner = importlib.util.module_from_spec(runner_spec)
    runner_spec.loader.exec_module(runner)
    policy = json.loads((SKILL_ROOT / "pipeline_policy.json").read_text(encoding="utf-8"))
    assert policy["image"]["allowed_providers"] == ["gpt_web", "third_party_api"]
    assert policy["image"]["human_review"] is False
    assert policy["image"]["model_visual_review"] is False

    def approved_image_action(provider: str) -> dict[str, object]:
        """Exercise routing only; never execute the returned external action."""
        with tempfile.TemporaryDirectory() as provider_temporary:
            batch = Path(provider_temporary) / provider
            item = batch / "V001_self-test_pending"
            task_dir = item / "_工作文件" / "任务状态"
            task_dir.mkdir(parents=True)
            product = Path(provider_temporary) / "产品参考.png"
            Image.new("RGB", (64, 64), "navy").save(product)
            api_config = {}
            approval_args = [
                "approve-start", "--batch", str(batch),
                "--approved-budget", "10", "--estimated-v01-total", "3",
                "--image-provider", provider,
            ]
            if provider == "third_party_api":
                api_config = {
                    "api_name": "Offline Example Images",
                    "base_url": "https://images.example.test/v1",
                    "model": "offline-image-v1",
                    "api_key_env": "SELF_TEST_IMAGE_API_KEY",
                    "unit_price_yuan": "0.20",
                }
                config_path = batch / "image-api-config.json"
                config_path.write_text(json.dumps(api_config), encoding="utf-8")
                approval_args.extend(["--image-api-config", str(config_path)])
            confirmation = {
                "total_videos": 1,
                "resolution": "2K",
                "duration_seconds": 15,
                "max_budget_yuan": "10",
                "unit_price_yuan": "3",
                "image_provider": provider,
                "image_api_config": api_config,
                "product_images": [str(product)],
            }
            (batch / "启动确认单.json").write_text(
                json.dumps(confirmation), encoding="utf-8"
            )
            (task_dir / "任务信息.json").write_text(
                json.dumps({"video_id": "V001", "retry_count": 0}), encoding="utf-8"
            )
            previous_key = os.environ.get("SELF_TEST_IMAGE_API_KEY")
            os.environ["SELF_TEST_IMAGE_API_KEY"] = "offline-only-placeholder"
            try:
                output = io.StringIO()
                with redirect_stdout(output):
                    assert runner.main(approval_args) == 0
                content_action = json.loads(output.getvalue())
                content_dir = Path(content_action["output_dir"])
                (content_dir / "V001.json").write_text(
                    json.dumps(valid_content, ensure_ascii=False), encoding="utf-8"
                )
                output = io.StringIO()
                with redirect_stdout(output):
                    assert runner.main([
                        "accept-content", "--batch", str(batch),
                        "--action-id", content_action["action_id"],
                        "--content-dir", str(content_dir),
                        "--profile", str(SKILL_ROOT / "profiles/爱优护电动轮椅_淘宝天猫光合.json"),
                    ]) == 0
                output = io.StringIO()
                with redirect_stdout(output):
                    assert runner.main(["next", "--batch", str(batch)]) == 0
                return json.loads(output.getvalue())
            finally:
                if previous_key is None:
                    os.environ.pop("SELF_TEST_IMAGE_API_KEY", None)
                else:
                    os.environ["SELF_TEST_IMAGE_API_KEY"] = previous_key

    assert approved_image_action("gpt_web")["kind"] == "GPT_WEB_IMAGE_REQUIRED"
    assert approved_image_action("third_party_api")["kind"] == "THIRD_PARTY_IMAGE_REQUIRED"
    with tempfile.TemporaryDirectory() as runtime_temporary:
        batch = Path(runtime_temporary) / "batch"
        item = batch / "V001_self-test_pending"
        task_dir = item / "_工作文件/任务状态"
        task_dir.mkdir(parents=True)
        product = Path(runtime_temporary) / "产品参考.png"
        Image.new("RGB", (64, 64), "navy").save(product)
        (batch / "启动确认单.json").write_text(json.dumps({"total_videos": 1, "resolution": "2K", "duration_seconds": 15, "max_budget_yuan": "10", "unit_price_yuan": "3", "image_provider": "gpt_web", "image_api_config": {}, "product_images": [str(product)]}), encoding="utf-8")
        (task_dir / "任务信息.json").write_text(json.dumps({"video_id": "V001", "retry_count": 0}), encoding="utf-8")
        def invoke(*args):
            output = io.StringIO()
            with redirect_stdout(output):
                assert runner.main(list(args)) == 0
            return json.loads(output.getvalue())
        action = invoke("approve-start", "--batch", str(batch), "--approved-budget", "10", "--estimated-v01-total", "3", "--image-provider", "gpt_web")
        assert action["kind"] == "BATCH_CONTENT_REQUIRED" and action["action_id"]
        content_dir = Path(action["output_dir"])
        (content_dir / "V001.json").write_text(json.dumps(valid_content, ensure_ascii=False), encoding="utf-8")
        invoke("accept-content", "--batch", str(batch), "--action-id", action["action_id"], "--content-dir", str(content_dir), "--profile", str(SKILL_ROOT / "profiles/爱优护电动轮椅_淘宝天猫光合.json"))
        for color in ("blue", "green", "orange"):
            action = invoke("next", "--batch", str(batch))
            assert action["kind"] == "GPT_WEB_IMAGE_REQUIRED"
            Image.new("RGB", (2160, 3840), color).save(action["output_path"])
            invoke("accept-image", "--batch", str(batch), "--video-id", "V001", "--artifact", action["artifact"], "--source", action["output_path"], "--action-id", action["action_id"])
        assert invoke("next", "--batch", str(batch))["kind"] == "LOCAL_WORK_REQUIRED"
        before = (batch / runner.STATE_FILENAME).read_bytes()
        assert invoke("run-local", "--batch", str(batch), "--dry-run")["kind"] == "DRY_RUN_COMPLETE"
        assert (batch / runner.STATE_FILENAME).read_bytes() == before
        state = json.loads(before)
        assert state["model_calls_batch"] == 1 and state["model_calls_by_video"] == {}
        assert state["image_calls_by_video"] == {"V001": 3}
        assert state["budget_ledger"] == {}
        # A stale terminal status cannot bypass a new whole-batch output audit.
        state["status"] = "COMPLETED"
        (batch / runner.STATE_FILENAME).write_text(json.dumps(state), encoding="utf-8")
        runner._write_task_info(item, {**runner._task_info(item), "status": "COMPLETED"})
        repair = invoke("next", "--batch", str(batch))
        assert repair["kind"] == "LOCAL_OUTPUT_REPAIR_REQUIRED"
        assert repair["paid_generation_allowed"] is False
        assert "视频.mp4" in repair["items"]["V001"]["missing"]
        assert invoke("run-local", "--batch", str(batch))["kind"] == "LOCAL_OUTPUT_REPAIR_REQUIRED"
        assert json.loads((batch / runner.STATE_FILENAME).read_text(encoding="utf-8"))["budget_ledger"] == {}
    # Auto V01 uses only offline fixtures, but must reach the persisted delivery state.
    with tempfile.TemporaryDirectory() as auto_temporary:
        auto_root = Path(auto_temporary)
        batch = auto_root / "auto-batch"
        item = batch / "V001_self-test_pending"
        (item / "_工作文件/任务状态").mkdir(parents=True)
        product = auto_root / "产品参考.png"
        Image.new("RGB", (64, 64), "navy").save(product)
        (batch / "启动确认单.json").write_text(
            json.dumps(
                {
                    "run_mode": "auto",
                    "startup_authorization": "initial_user_reply",
                    "total_videos": 1,
                    "resolution": "768P",
                    "duration_seconds": 15,
                    "max_budget_yuan": "5.00",
                    "prices_by_video": {"V001": "3.00"},
                    "image_provider": "gpt_web",
                    "image_api_config": {},
                    "product_images": [str(product)],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (item / "_工作文件/任务状态/任务信息.json").write_text(
            json.dumps({"video_id": "V001", "retry_count": 0}), encoding="utf-8"
        )
        previous_tempdir = runner.tempfile.gettempdir
        runner.tempfile.gettempdir = lambda: str(auto_root / "unrelated-temp")
        try:
            def auto_invoke(*args):
                output = io.StringIO()
                with redirect_stdout(output):
                    assert runner.main(list(args)) == 0
                return json.loads(output.getvalue())

            content_action = auto_invoke("next", "--batch", str(batch))
            assert content_action["kind"] == "BATCH_CONTENT_REQUIRED"
            content_dir = Path(content_action["output_dir"])
            content_dir.mkdir(parents=True, exist_ok=True)
            (content_dir / "V001.json").write_text(
                json.dumps(valid_content, ensure_ascii=False), encoding="utf-8"
            )
            auto_invoke(
                "accept-content", "--batch", str(batch),
                "--action-id", content_action["action_id"],
                "--content-dir", str(content_dir),
                "--profile", str(SKILL_ROOT / "profiles/爱优护电动轮椅_淘宝天猫光合.json"),
            )
            for index, color in enumerate(("navy", "green", "orange")):
                image_action = auto_invoke("next", "--batch", str(batch))
                assert image_action["kind"] == "GPT_WEB_IMAGE_REQUIRED"
                image = Path(image_action["output_path"])
                Image.new("RGB", (2160, 3840), color).save(image)
                auto_invoke(
                    "accept-image", "--batch", str(batch),
                    "--video-id", "V001", "--artifact", image_action["artifact"],
                    "--source", str(image), "--action-id", image_action["action_id"],
                )
            assert auto_invoke("next", "--batch", str(batch))["kind"] == "LOCAL_WORK_REQUIRED"

            def offline_runner(batch_dir, item_dir, state, **kwargs):
                info = runner._task_info(item_dir)
                info.update({"task_id": "self-test-v01", "request_hash": "self-test-request", "submission_pending": False})
                runner._write_task_info(item_dir, info)
                state.budget_ledger["V001:V01"] = {
                    "cost": "3.00", "status": "spent", "task_id": "self-test-v01",
                    "request_hash": "self-test-request",
                }
                candidate = item_dir / "_工作文件/生成过程/视频候选.mp4"
                candidate.write_bytes(b"offline-auto-v01")
                technical = {
                    "ok": True, "full_decode": True, "has_audio": True,
                    "duration": 15.0, "width": 1280, "height": 720,
                    "sha256": runner._sha256(candidate), "candidate": str(candidate.resolve()),
                }
                return {"ok": True, "task_id": "self-test-v01", "candidate": str(candidate), "technical": technical}

            original_autodl = runner.run_autodl_item
            runner.run_autodl_item = offline_runner
            try:
                delivered = auto_invoke("run-local", "--batch", str(batch))
            finally:
                runner.run_autodl_item = original_autodl
            assert delivered["kind"] == "V01_DELIVERED", delivered
            assert delivered["status"] == "WAITING_USER_FEEDBACK"
            row = delivered["items"][0]
            video = Path(row["video_path"])
            item_dir = Path(row["item_dir"])
            assert video.is_absolute() and video.is_file()
            assert item_dir.is_absolute() and item_dir.is_dir()
            assert video.parent == item_dir
            assert runner._sha256(video) == row["sha256"] == row["technical"]["sha256"]
            assert json.loads((batch / runner.STATE_FILENAME).read_text(encoding="utf-8"))["status"] == "WAITING_USER_FEEDBACK"
        finally:
            runner.tempfile.gettempdir = previous_tempdir
    print("product-video-pipeline 自检通过（未联网、未产生费用）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
