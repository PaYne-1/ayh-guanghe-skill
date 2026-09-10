#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


IMAGE_PROVIDERS = ("codex", "chatgpt_web", "third_party_api")
IMAGE_API_FIELDS = (
    "api_name", "base_url", "model", "api_key_env",
    "unit_price_yuan",
)


def policy_digest(policy: Mapping[str, object]) -> str:
    encoded = json.dumps(
        policy,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def positive_amount(value: object, field: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是有效正数金额") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{field} 必须是有效正数金额")
    return amount


def normalize_image_provider(value: object) -> str:
    if value == "gpt_web":
        return "gpt_web"
    if not isinstance(value, str) or value not in IMAGE_PROVIDERS:
        raise ValueError("图片渠道必须明确选择 codex、chatgpt_web 或 third_party_api")
    return value


def normalize_image_api_config(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("third_party_api 图片渠道必须提供 image_api_config")
    forbidden = {"api_key", "secret", "token", "authorization"} & set(value)
    if forbidden:
        raise ValueError("不得在配置中保存 API 密钥明文，只能填写 api_key_env")
    normalized = {}
    for key in IMAGE_API_FIELDS[:4]:
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"image_api_config 缺少有效字段：{key}")
        normalized[key] = item.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized["api_key_env"]):
        raise ValueError("image_api_config.api_key_env 必须是有效的环境变量名")
    parsed_base_url = urlparse(normalized["base_url"])
    if (
        parsed_base_url.scheme != "https"
        or not parsed_base_url.hostname
        or parsed_base_url.username is not None
        or parsed_base_url.password is not None
        or parsed_base_url.query
        or parsed_base_url.fragment
    ):
        raise ValueError("image_api_config.base_url 必须使用 https://")
    for key in IMAGE_API_FIELDS[4:]:
        amount = positive_amount(value.get(key), f"image_api_config.{key}")
        normalized[key] = str(amount)
    return normalized


def load_policy(skill_root: Path) -> dict[str, Any]:
    policy_path = skill_root / "pipeline_policy.json"
    value = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("pipeline_policy.json 版本无效")
    image = value.get("image")
    if not isinstance(image, dict) or image.get("allowed_providers") != list(IMAGE_PROVIDERS):
        raise ValueError("图片渠道规则无效")
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
    if approvals != {
        "auto_initial_response_authorizes_v01": True,
        "learning_startup_budget": True,
        "v02": "user_required",
        "final_video": {"auto": "deliver_without_review", "learning": "user_required"},
    }:
        raise ValueError("授权规则无效")
    autodl = value.get("autodl")
    if not isinstance(autodl, dict) or autodl.get("workflow_id") != "minimax_h3_lightx2v_v5_15s" or autodl.get("duration_seconds") != 15:
        raise ValueError("AutoDL 工作流规则无效")
    for key in ("poll_interval_seconds", "poll_timeout_seconds"):
        if type(autodl.get(key)) is not int or autodl[key] <= 0:
            raise ValueError(f"AutoDL 轮询规则无效：{key}")
    states = {"WAITING_START_APPROVAL", "RUNNING_AUTOMATICALLY", "WAITING_PAID_APPROVAL", "GENERATING", "WAITING_FINAL_REVIEW", "WAITING_USER_FEEDBACK", "WAITING_RERUN_APPROVAL", "COMPLETED", "BLOCKED"}
    if not isinstance(value.get("states"), list) or set(value["states"]) != states or len(value["states"]) != len(states):
        raise ValueError("状态规则无效")
    return value
