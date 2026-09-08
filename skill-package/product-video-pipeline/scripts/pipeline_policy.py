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
    fixed = {"human_review": False, "model_visual_review": False, "target_width": 2160, "target_height": 3840}
    for key, expected in fixed.items():
        if type(image.get(key)) is not type(expected) or image.get(key) != expected:
            raise ValueError(f"图片规则无效：{key}")
    if type(image.get("download_retries")) is not int or image["download_retries"] not in {0, 1}:
        raise ValueError("图片重试次数必须是 0 或 1")
    limits = value.get("model_budget")
    keys = ("per_video", "batch_content_calls", "content_correction_calls", "diagnostic_calls", "image_calls_per_video")
    if not isinstance(limits, dict) or any(type(limits.get(k)) is not int or limits[k] < 0 for k in keys):
        raise ValueError("模型预算配置无效")
    approvals = value.get("approvals")
    if approvals != {"startup_budget": True, "v01_within_budget": "automatic", "v02": "user_required", "final_video": "user_required"}:
        raise ValueError("授权规则无效")
    autodl = value.get("autodl")
    if not isinstance(autodl, dict) or autodl.get("workflow_id") != "minimax_h3_lightx2v_v5_15s" or autodl.get("duration_seconds") != 15:
        raise ValueError("AutoDL 工作流规则无效")
    for key in ("poll_interval_seconds", "poll_timeout_seconds"):
        if type(autodl.get(key)) is not int or autodl[key] <= 0:
            raise ValueError(f"AutoDL 轮询规则无效：{key}")
    states = {"WAITING_START_APPROVAL", "RUNNING_AUTOMATICALLY", "WAITING_PAID_APPROVAL", "GENERATING", "WAITING_FINAL_REVIEW", "WAITING_RERUN_APPROVAL", "COMPLETED", "BLOCKED"}
    if not isinstance(value.get("states"), list) or set(value["states"]) != states or len(value["states"]) != len(states):
        raise ValueError("状态规则无效")
    return value
