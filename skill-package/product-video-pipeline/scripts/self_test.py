#!/usr/bin/env python3
"""No-network, no-charge self-test for the portable skill package."""

from __future__ import annotations

import json
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
    for command in ("record-issue", "validate-learning", "prepare-node-rules"):
        assert command in workflow_help
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
            json.dumps({"video_id": "V001", "retry_count": 1}), encoding="utf-8"
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
                    "prompt": "固定镜头",
                    "duration": 15,
                    "resolution": "768p竖",
                    "ref_image_0": "data:image/png;base64,AAAA",
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
    print("product-video-pipeline 自检通过（未联网、未产生费用）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
