#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def policy_digest(policy: Mapping[str, object]) -> str:
    encoded = json.dumps(
        policy,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_policy(skill_root: Path) -> dict[str, Any]:
    policy_path = skill_root / "pipeline_policy.json"
    value = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("pipeline_policy.json 版本无效")
    image = value.get("image")
    if not isinstance(image, dict) or image.get("provider") != "gpt_web":
        raise ValueError("图片渠道必须固定为 gpt_web")
    return value
