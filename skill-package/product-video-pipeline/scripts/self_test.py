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
        "references/install.md",
        "scripts/workflow_cli.py",
        "scripts/autodl_h3.py",
        "scripts/render_cover.py",
    )
    missing = [path for path in required if not (SKILL_ROOT / path).exists()]
    if missing:
        print("缺少文件：" + ", ".join(missing), file=sys.stderr)
        return 1
    subprocess.run([sys.executable, str(SKILL_ROOT / "scripts" / "workflow_cli.py"), "--help"], check=True, capture_output=True)
    with tempfile.TemporaryDirectory() as temporary:
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
        child_environment = dict(os.environ)
        child_environment["PYTHONUTF8"] = "1"
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
