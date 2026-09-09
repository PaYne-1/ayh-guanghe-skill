#!/usr/bin/env python3

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

from PIL import Image

STATE_FILENAME = "流水线状态.json"
VALID_STATES = {
    "WAITING_START_APPROVAL",
    "RUNNING_AUTOMATICALLY",
    "WAITING_PAID_APPROVAL",
    "GENERATING",
    "WAITING_FINAL_REVIEW",
    "WAITING_RERUN_APPROVAL",
    "COMPLETED",
    "BLOCKED",
}
IMAGE_ACTION_KINDS = {"GPT_WEB_IMAGE_REQUIRED", "THIRD_PARTY_IMAGE_REQUIRED"}


@dataclass(frozen=True)
class ExternalAction:
    """A compact hand-off to an external actor; prompt content remains on disk."""

    kind: str
    video_id: Optional[str] = None
    artifact: Optional[str] = None
    prompt_path: Optional[str] = None
    output_path: Optional[str] = None
    reason: Optional[str] = None


class ModelBudgetExceeded(RuntimeError):
    pass


_LOCKS: dict[str, threading.RLock] = {}
_LOCK_DEPTH = threading.local()


@contextmanager
def exclusive_lock(path: Path):
    """OS-released on process exit; a persisted pending POST still fails closed."""
    key = str(path.resolve())
    local = _LOCKS.setdefault(key, threading.RLock())
    with local:
        depths = getattr(_LOCK_DEPTH, "depths", {})
        _LOCK_DEPTH.depths = depths
        if depths.get(key, 0):
            depths[key] += 1
            try:
                yield
            finally:
                depths[key] -= 1
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("另一执行进程正在处理该批次；稍后恢复") from exc
            depths[key] = 1
            try:
                yield
            finally:
                depths.pop(key, None)
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_policy_module():
    path = Path(__file__).with_name("pipeline_policy.py")
    spec = importlib.util.spec_from_file_location("product_video_pipeline_policy", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 pipeline_policy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_prompt_contract():
    """Load the sibling contract module without depending on package installation."""
    path = Path(__file__).with_name("generation_prompt_contract.py")
    spec = importlib.util.spec_from_file_location(
        "product_video_generation_prompt_contract", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 generation_prompt_contract.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _state_path(batch_dir: Path) -> Path:
    return batch_dir / STATE_FILENAME


@dataclass
class RunnerState:
    schema_version: int
    policy_digest: str
    status: str
    approved_budget: str = ""
    estimated_v01_total: str = ""
    rerun_budget_by_video: dict[str, str] = field(default_factory=dict)
    model_calls_batch: int = 0
    model_calls_by_video: dict[str, int] = field(default_factory=dict)
    image_failures: dict[str, int] = field(default_factory=dict)
    completed_nodes: dict[str, list[str]] = field(default_factory=dict)
    pending_action: Optional[dict[str, Any]] = None
    human_gate: Optional[dict[str, Any]] = None
    blocked_reason: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    approved_manifest: dict[str, Any] = field(default_factory=dict)
    manifest_digest: str = ""
    budget_ledger: dict[str, Any] = field(default_factory=dict)
    image_budget_ledger: dict[str, dict[str, str]] = field(default_factory=dict)
    payload_bindings: dict[str, Any] = field(default_factory=dict)
    model_actions: dict[str, Any] = field(default_factory=dict)
    model_usage: dict[str, int] = field(default_factory=dict)
    image_calls_by_video: dict[str, int] = field(default_factory=dict)
    item_failures: dict[str, Any] = field(default_factory=dict)
    profile_path: str = ""

    @classmethod
    def new(cls, digest: str) -> "RunnerState":
        return cls(1, digest, "WAITING_START_APPROVAL")


def save_state(batch_dir: Path, state: RunnerState) -> Path:
    return _atomic_json(_state_path(batch_dir), asdict(state))


def _validate_state(value: object) -> RunnerState:
    if not isinstance(value, dict):
        raise ValueError("流水线状态必须为对象")
    try:
        state = RunnerState(**value)
    except TypeError as exc:
        raise ValueError("流水线状态字段无效") from exc
    if type(state.schema_version) is not int or state.schema_version != 1 or not isinstance(state.status, str) or state.status not in VALID_STATES:
        raise ValueError("流水线状态 schema/status 无效")
    if type(state.model_calls_batch) is not int or state.model_calls_batch < 0:
        raise ValueError("流水线模型计数无效")
    for name in ("model_calls_by_video", "image_failures", "model_usage", "image_calls_by_video"):
        mapping = getattr(state, name)
        if not isinstance(mapping, dict) or any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in mapping.items()):
            raise ValueError(f"流水线状态计数无效：{name}")
    for name in ("rerun_budget_by_video", "completed_nodes", "approved_manifest", "budget_ledger", "image_budget_ledger", "payload_bindings", "model_actions", "item_failures"):
        if not isinstance(getattr(state, name), dict):
            raise ValueError(f"流水线状态字段无效：{name}")
    if any(not isinstance(v, list) or any(not isinstance(n, str) for n in v) for v in state.completed_nodes.values()):
        raise ValueError("流水线状态节点列表无效")
    for name in ("policy_digest", "approved_budget", "estimated_v01_total", "blocked_reason", "manifest_digest", "profile_path"):
        if not isinstance(getattr(state, name), str):
            raise ValueError(f"流水线状态字段无效：{name}")
    if not isinstance(state.history, list) or any(not isinstance(v, dict) for v in state.history):
        raise ValueError("流水线状态历史无效")
    for name in ("pending_action", "human_gate"):
        action = getattr(state, name)
        if action is not None and (not isinstance(action, dict) or not isinstance(action.get("kind"), str)):
            raise ValueError(f"流水线状态待执行动作无效：{name}")
    # v1.7.0 initially shared this slot. Migrate durable human queues once.
    if (state.pending_action or {}).get("kind", "").startswith("USER_"):
        if state.human_gate is None:
            state.human_gate = state.pending_action
        state.pending_action = None
    for row in state.model_actions.values():
        if not isinstance(row, dict) or row.get("status") not in {"reserved", "accepted", "failed"} or not isinstance(row.get("kind"), str):
            raise ValueError("流水线状态模型动作无效")
    for key, row in state.budget_ledger.items():
        if not isinstance(row, dict) or row.get("status") not in {"reserved", "spent", "unknown"}:
            raise ValueError("流水线状态费用台账无效")
        _positive_authorization_amount(row.get("cost"), f"状态费用 {key}")
    for key, row in state.image_budget_ledger.items():
        if (
            not isinstance(key, str)
            or not isinstance(row, dict)
            or row.get("status") not in {"reserved", "spent", "unknown", "released"}
            or row.get("action_id") != key
            or row.get("provider") != "third_party_api"
        ):
            raise ValueError("流水线状态图片 API 费用台账无效")
        cost = _positive_authorization_amount(row.get("cost"), f"状态图片 API 费用 {key}")
        if str(cost) != row.get("cost"):
            raise ValueError("流水线状态图片 API 费用必须为规范金额")
    return state


def load_or_create_state(batch_dir: Path, policy: dict[str, object]) -> RunnerState:
    path = _state_path(batch_dir)
    digest = _load_policy_module().policy_digest(policy)
    if not path.exists():
        state = RunnerState.new(digest)
        save_state(batch_dir, state)
        return state
    state = _validate_state(json.loads(path.read_text(encoding="utf-8")))
    if state.policy_digest != digest:
        raise ValueError("批次规则摘要与当前 pipeline_policy.json 不一致")
    return state


def transition(state: RunnerState, target: str, *, reason: str = "") -> RunnerState:
    if target not in VALID_STATES:
        raise ValueError(f"未知状态：{target}")
    previous = state.status
    state.status = target
    state.blocked_reason = reason if target == "BLOCKED" else ""
    state.history.append(
        {"at": _now(), "from": previous, "to": target, "reason": reason}
    )
    return state


def _load_workflow_cli():
    path = Path(__file__).with_name("workflow_cli.py")
    spec = importlib.util.spec_from_file_location("product_video_workflow_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 workflow_cli.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_autodl():
    path = Path(__file__).with_name("autodl_h3.py")
    spec = importlib.util.spec_from_file_location("product_video_autodl_h3", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 autodl_h3.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _task_info(item_dir: Path) -> dict[str, object]:
    path = item_dir / "_工作文件" / "任务状态" / "任务信息.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_task_info(item_dir: Path, info: dict[str, object]) -> Path:
    path = item_dir / "_工作文件" / "任务状态" / "任务信息.json"
    _atomic_json(path, info)
    table_path = item_dir.parent / "批次任务表.json"
    table = json.loads(table_path.read_text(encoding="utf-8")) if table_path.is_file() else {"items": []}
    video_id = item_dir.name.split("_", 1)[0]
    row = next((row for row in table["items"] if row.get("video_id") == video_id), None)
    if row is None:
        row = {"video_id": video_id}
        table["items"].append(row)
    row.update(info)
    _atomic_json(table_path, table)
    return path


def _record_execution(item_dir: Path, name: str, value: object) -> Path:
    return _atomic_json(item_dir / "_工作文件" / "任务状态" / name, value)


def _persist_pending_submission(
    item_dir: Path, info: dict[str, object], request_hash: str
) -> dict[str, object]:
    pending = dict(info)
    pending.update(
        {
            "request_hash": request_hash,
            "submission_pending": True,
            "status": "SUBMISSION_PENDING",
            "submission_pending_at": _now(),
        }
    )
    _write_task_info(item_dir, pending)
    return pending


def _persist_submission_response(
    item_dir: Path,
    info: dict[str, object],
    submitted: dict[str, object],
) -> dict[str, object]:
    response_info = dict(info)
    response_info.update(
        {
            "task_id": submitted["task_id"],
            "request_id": submitted.get("request_id"),
            "request_hash": submitted["request_hash"],
            "submission_pending": True,
            "status": "SUBMISSION_RESPONSE_PENDING_RECORD",
        }
    )
    _write_task_info(item_dir, response_info)
    return response_info


def _reconciliation_required(
    state: RunnerState,
    item_dir: Path,
    info: dict[str, object],
    reason: str,
) -> dict[str, object]:
    blocked_info = dict(info)
    blocked_info.update(
        {
            "submission_pending": True,
            "status": "RECONCILIATION_REQUIRED",
            "reconciliation_reason": reason,
        }
    )
    _write_task_info(item_dir, blocked_info)
    blocked_reason = f"AutoDL 提交结果需要人工核对：{reason}"
    video_id = item_dir.name.split("_", 1)[0]
    state.item_failures[video_id] = {"kind": "reconciliation", "reason": blocked_reason}
    key = _attempt_key(item_dir)
    if key in state.budget_ledger:
        state.budget_ledger[key]["status"] = "unknown"
    save_state(item_dir.parent, state)
    result: dict[str, object] = {
        "ok": False,
        "status": "RECONCILIATION_REQUIRED",
        "request_hash": str(blocked_info.get("request_hash") or ""),
        "reason": blocked_reason,
    }
    if blocked_info.get("task_id"):
        result["task_id"] = str(blocked_info["task_id"])
    return result


def _submit_item(
    item_dir: Path, api_key: Optional[str], dry_run: bool
) -> dict[str, object]:
    autodl = _load_autodl()
    payload = item_dir / "_工作文件" / "任务状态" / "提交请求.json"
    return autodl.submit_payload(
        payload,
        api_key=api_key,
        dry_run=dry_run,
        confirm_paid=not dry_run,
        workflow_id=autodl.WORKFLOW_ID,
        auth_scheme=os.environ.get("AUTODL_AUTH_SCHEME", "bearer"),
        response_path=item_dir / "_工作文件/任务状态/AutoDL原始响应.json",
    )


def _poll_item(task_id: str, api_key: Optional[str]) -> dict[str, object]:
    autodl = _load_autodl()
    policy = _load_policy_module().load_policy(Path(__file__).resolve().parents[1])
    response = autodl.poll_task(
        task_id, api_key=api_key,
        auth_scheme=os.environ.get("AUTODL_AUTH_SCHEME", "bearer"),
        interval_seconds=policy["autodl"]["poll_interval_seconds"],
        max_wait_seconds=policy["autodl"]["poll_timeout_seconds"],
    )
    status = autodl.task_status(response)
    result: dict[str, object] = {"status": status, "response": response}
    if status in {"success", "succeeded", "completed"}:
        result["url"] = autodl.first_result_url(response)
    return result


def _download_item(url: str, item_dir: Path) -> Path:
    autodl = _load_autodl()
    return autodl.download_atomic(
        url, item_dir / "_工作文件" / "生成过程" / "视频候选.mp4"
    )


def assert_paid_submit_allowed(
    state: RunnerState, task_info: dict[str, object], video_id: str
) -> None:
    if state.status not in {"RUNNING_AUTOMATICALLY", "GENERATING"}:
        raise PermissionError("当前状态不允许付费提交")
    raw_retry_count = task_info.get("retry_count", 0)
    try:
        parsed_retry_count = Decimal(str(raw_retry_count))
    except (InvalidOperation, ValueError) as exc:
        raise PermissionError("付费提交版本无效；仅允许 V01 或 V02") from exc
    if (
        not parsed_retry_count.is_finite()
        or parsed_retry_count != parsed_retry_count.to_integral_value()
        or int(parsed_retry_count) not in {0, 1}
    ):
        raise PermissionError("禁止提交 V03 或无效视频版本")
    retry_count = int(parsed_retry_count)
    if retry_count == 0:
        if not state.approved_budget or not state.estimated_v01_total:
            raise PermissionError("缺少 V01 批次预算授权或预计总价")
        approved = _positive_authorization_amount(
            state.approved_budget, "V01 批次预算授权"
        )
        estimated = _positive_authorization_amount(
            state.estimated_v01_total, "V01 预计总价"
        )
        if estimated > approved:
            raise PermissionError("V01 预计总价超过批准预算")
        return
    if video_id not in state.rerun_budget_by_video:
        raise PermissionError(f"{video_id} 缺少 V02 单独付费授权")
    _positive_authorization_amount(
        state.rerun_budget_by_video[video_id], f"{video_id} 的 V02 单独付费授权金额"
    )


def _positive_authorization_amount(value: object, label: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PermissionError(f"{label}必须是有限正数") from exc
    if not amount.is_finite() or amount <= 0:
        raise PermissionError(f"{label}必须是有限正数")
    return amount


def _confirmation_manifest(batch_dir: Path) -> dict[str, object]:
    path = batch_dir / "启动确认单.json"
    if not path.is_file():
        raise PermissionError("缺少启动确认单和费用清单")
    confirmation = json.loads(path.read_text(encoding="utf-8"))
    policy_module = _load_policy_module()
    image_provider = policy_module.normalize_image_provider(confirmation.get("image_provider"))
    if image_provider == "gpt_web":
        if confirmation.get("image_api_config") not in (None, {}):
            raise PermissionError("gpt_web 图片渠道不得携带第三方 API 配置")
        image_api_config = {}
    else:
        image_api_config = policy_module.normalize_image_api_config(
            confirmation.get("image_api_config")
        )
    ids = [item.name.split("_", 1)[0] for item in _video_items(batch_dir)]
    if not ids or len(ids) != len(set(ids)) or confirmation.get("total_videos") != len(ids):
        raise PermissionError("启动确认单项目数量/ID与实际批次不一致")
    resolution = confirmation.get("resolution")
    if resolution not in {"768P", "2K"} or confirmation.get("duration_seconds", 15) != 15:
        raise PermissionError("启动确认单视频配置无效")
    prices = confirmation.get("prices_by_video")
    if prices is None:
        price = confirmation.get("unit_price_yuan")
        if price is None and isinstance(confirmation.get("live_price"), dict):
            price = confirmation["live_price"].get("unit_price_yuan")
        prices = {video_id: price for video_id in ids}
    if not isinstance(prices, dict) or set(prices) != set(ids):
        raise PermissionError("启动费用清单必须逐条覆盖全部项目")
    prices = {video_id: str(_positive_authorization_amount(prices[video_id], f"{video_id} 单价")) for video_id in ids}
    return {
        "video_ids": ids, "item_count": len(ids), "resolution": resolution,
        "duration_seconds": 15, "workflow_id": _load_autodl().WORKFLOW_ID,
        "price_by_video": prices,
        "estimated_v01_total": str(sum((Decimal(p) for p in prices.values()), Decimal("0"))),
        "max_budget_yuan": str(_positive_authorization_amount(confirmation.get("max_budget_yuan"), "启动预算")),
        "image_provider": image_provider,
        "image_api_config": image_api_config,
    }


def _approved_image_config(
    confirmation: dict[str, object], provider: str, config_path: Optional[Path]
) -> tuple[str, dict[str, str]]:
    policy_module = _load_policy_module()
    selected = policy_module.normalize_image_provider(provider)
    declared = policy_module.normalize_image_provider(confirmation.get("image_provider"))
    if selected != declared:
        raise PermissionError("批准的图片渠道与启动确认单不一致；切换渠道必须新建批次")
    if selected == "gpt_web":
        if config_path is not None or confirmation.get("image_api_config") not in (None, {}):
            raise ValueError("gpt_web 图片渠道不得携带第三方 API 配置")
        return selected, {}
    if config_path is None or not config_path.is_file():
        raise ValueError("third_party_api 必须提供 --image-api-config")
    supplied = policy_module.normalize_image_api_config(
        json.loads(config_path.read_text(encoding="utf-8"))
    )
    declared_config = policy_module.normalize_image_api_config(
        confirmation.get("image_api_config")
    )
    if supplied != declared_config:
        raise PermissionError("图片 API 配置与启动确认单不一致")
    if not os.environ.get(supplied["api_key_env"]):
        raise PermissionError(f"缺少图片 API 密钥环境变量：{supplied['api_key_env']}")
    return selected, supplied


def validate_approved_manifest(batch_dir: Path, state: RunnerState) -> None:
    if not state.approved_manifest or not state.manifest_digest:
        raise PermissionError("缺少已批准的项目费用清单")
    manifest = _confirmation_manifest(batch_dir)
    if manifest != state.approved_manifest or _load_policy_module().policy_digest(manifest) != state.manifest_digest:
        raise PermissionError("实际项目或配置与已批准清单不一致")
    if Decimal(state.estimated_v01_total) != Decimal(str(manifest["estimated_v01_total"])):
        raise PermissionError("预计总价与已批准清单不一致")


def _attempt_key(item_dir: Path) -> str:
    return f"{item_dir.name.split('_', 1)[0]}:V{_item_retry_count(item_dir) + 1:02d}"


def _payload_binding(batch_dir: Path, item_dir: Path, state: RunnerState) -> dict[str, object]:
    validate_approved_manifest(batch_dir, state)
    workflow = _load_workflow_cli()
    payload_path = item_dir / "_工作文件/任务状态/提交请求.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    _load_autodl().validate_first_last_payload(payload)
    expected_resolution = {"768P": "768p竖", "2K": "2K"}[state.approved_manifest["resolution"]]
    if payload.get("resolution") != expected_resolution or payload.get("duration") != 15:
        raise PermissionError("提交配置与批准清单不一致")
    hashes = {}
    for field, name in (("first_frame", "分镜图.png"), ("last_frame", "尾帧图.png")):
        image = workflow.validated_promoted_artifact_path(item_dir, name)
        if image is None:
            raise PermissionError(f"提交缺少有效已授权图片：{name}")
        with Image.open(image) as decoded:
            decoded.load()
            if decoded.size != (2160, 3840):
                raise PermissionError("提交图片尺寸与批准规则不一致")
        value = payload.get(field)
        if not isinstance(value, str) or not value.startswith("data:image/png;base64,"):
            raise PermissionError("自动提交必须绑定本地有效图片的 data URI")
        try:
            payload_bytes = base64.b64decode(value.split(",", 1)[1], validate=True)
        except ValueError as exc:
            raise PermissionError("提交图片编码无效") from exc
        hashes[field] = _sha256(image)
        if hashlib.sha256(payload_bytes).hexdigest() != hashes[field]:
            raise PermissionError("提交图片哈希与已授权图片不一致")
    if hashes["first_frame"] == hashes["last_frame"]:
        raise PermissionError("首尾帧哈希必须不同")
    return {"payload_sha256": _load_autodl()._request_hash(payload), "frame_sha256": hashes, "resolution": expected_resolution, "duration": 15, "workflow_id": state.approved_manifest["workflow_id"]}


def _reserve_payment(batch_dir: Path, item_dir: Path, state: RunnerState, request_hash: str) -> None:
    video_id = item_dir.name.split("_", 1)[0]
    assert_paid_submit_allowed(state, _task_info(item_dir), video_id)
    binding = _payload_binding(batch_dir, item_dir, state)
    key = _attempt_key(item_dir)
    expected = state.payload_bindings.get(key)
    if expected is not None and expected != binding:
        raise PermissionError("提交参数或首尾帧哈希在绑定后发生改变")
    cost = Decimal(state.approved_manifest["price_by_video"][video_id])
    if key.endswith("V02") and Decimal(state.rerun_budget_by_video[video_id]) != cost:
        raise PermissionError("V02 授权金额必须与该视频预计费用完全一致")
    if key in state.budget_ledger:
        raise PermissionError("本版本已有费用保留记录；必须核对原任务，禁止重复付费")
    total = sum((Decimal(row["cost"]) for row in state.budget_ledger.values()), Decimal("0"))
    limit = Decimal(state.approved_budget) + sum((Decimal(v) for v in state.rerun_budget_by_video.values()), Decimal("0"))
    if total + cost > limit:
        raise PermissionError("累计已消费/保留费用超过授权预算")
    state.payload_bindings[key] = binding
    state.budget_ledger[key] = {"cost": str(cost), "status": "reserved", "request_hash": request_hash, "at": _now(), "binding": binding}
    save_state(batch_dir, state)


def _expected_video_resolution(
    batch_dir: Path, item_dir: Path, task_info: dict[str, object]
) -> str:
    candidates = (
        item_dir / "_工作文件" / "任务状态" / "提交请求.json",
        batch_dir / "启动确认单.json",
    )
    for path in candidates:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("resolution"):
                return str(data["resolution"])
    return str(task_info.get("resolution") or "768P")


def validate_video_file(path: Path, expected_resolution: str) -> dict[str, object]:
    path = path.resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("视频候选不存在或为空")
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise ValueError("视频候选无法通过 ffprobe 解码")
    probe = json.loads(completed.stdout)
    streams = probe.get("streams", [])
    video = next((row for row in streams if row.get("codec_type") == "video"), None)
    audio = next((row for row in streams if row.get("codec_type") == "audio"), None)
    if video is None or audio is None:
        raise ValueError("视频候选必须同时包含可解码画面和音轨")
    width = int(video.get("width", 0))
    height = int(video.get("height", 0))
    duration = float(probe.get("format", {}).get("duration", 0))
    expected = {"768P": (768, 1365), "768p竖": (768, 1365), "2K": (1440, 2560)}
    if expected_resolution not in expected:
        raise ValueError(f"未知视频分辨率：{expected_resolution}")
    if not 13 <= duration <= 17:
        raise ValueError("视频时长必须在 13–17 秒技术容差内")
    if height <= width or (width, height) != expected[expected_resolution]:
        raise ValueError("视频方向或分辨率不符合启动确认单")
    decoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", "-err_detect", "explode", "-i", str(path),
         "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
        check=False, capture_output=True, text=True, encoding="utf-8",
    )
    if decoded.returncode != 0:
        raise ValueError("视频候选全片画面/音轨解码失败")
    return {
        "ok": True,
        "duration": duration,
        "width": width,
        "height": height,
        "has_audio": True,
        "sha256": _sha256(path),
        "full_decode": True,
        "candidate": str(path),
        "expected_resolution": expected_resolution,
        "probe": probe,
    }


def run_autodl_item(
    batch_dir: Path,
    item_dir: Path,
    state: RunnerState,
    *,
    api_key: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, object]:
    if dry_run:
        payload = item_dir / "_工作文件/任务状态/提交请求.json"
        if not payload.is_file():
            return {"ok": False, "dry_run": True, "reason": "提交请求尚未准备"}
        preview = _submit_item(item_dir, api_key, dry_run=True)
        return {"ok": True, "dry_run": True, "request_hash": preview["request_hash"]}
    with exclusive_lock(batch_dir / ".pipeline.lock"):
        if _state_path(batch_dir).is_file() and state.approved_manifest:
            fresh = _validate_state(json.loads(_state_path(batch_dir).read_text(encoding="utf-8")))
            state.__dict__.update(fresh.__dict__)
        return _run_autodl_locked(batch_dir, item_dir, state, api_key=api_key)


def _run_autodl_locked(
    batch_dir: Path, item_dir: Path, state: RunnerState, *, api_key: Optional[str]
) -> dict[str, object]:
    video_id = item_dir.name.split("_", 1)[0]
    info = _task_info(item_dir)
    task_id = str(info.get("task_id") or "")
    submitted: dict[str, object] = {}
    if not task_id and (info.get("submission_pending") or info.get("request_hash")):
        return _reconciliation_required(
            state,
            item_dir,
            info,
            str(info.get("reconciliation_reason") or "存在未核对的提交请求身份"),
        )
    if not task_id:
        api_key = api_key or os.environ.get("AUTODL_API_KEY")
        if not api_key:
            raise ValueError("未设置 AUTODL_API_KEY；尚未创建任何付费提交标记")
        if os.environ.get("AUTODL_AUTH_SCHEME", "bearer") not in {"bearer", "raw"}:
            raise ValueError("AUTODL_AUTH_SCHEME 只能是 bearer 或 raw")
        preview = _submit_item(item_dir, api_key, dry_run=True)
        request_hash = str(preview.get("request_hash") or "")
        if not request_hash:
            raise ValueError("AutoDL 提交预览缺少 request_hash")
        _reserve_payment(batch_dir, item_dir, state, request_hash)
        _record_execution(item_dir, "提交预览.json", preview)
        info = _persist_pending_submission(item_dir, info, request_hash)
        try:
            submitted = _submit_item(item_dir, api_key, dry_run=False)
            task_id = str(submitted.get("task_id") or "")
            response_hash = str(submitted.get("request_hash") or "")
            if not task_id:
                raise RuntimeError("AutoDL 付费响应缺少 task_id")
            if response_hash != request_hash:
                raise RuntimeError("AutoDL 付费响应 request_hash 与提交标记不一致")
            info = _persist_submission_response(item_dir, info, submitted)
            _record_execution(item_dir, "AutoDL提交结果.json", submitted)
            workflow = _load_workflow_cli()
            workflow.record_task(
                batch_dir,
                video_id,
                task_id,
                request_id=submitted.get("request_id"),
                request_hash=request_hash,
                estimated_cost_yuan=state.budget_ledger[_attempt_key(item_dir)]["cost"],
            )
            state.budget_ledger[_attempt_key(item_dir)]["status"] = "spent"
            state.budget_ledger[_attempt_key(item_dir)]["task_id"] = task_id
            save_state(batch_dir, state)
        except Exception as exc:
            _record_execution(item_dir, "提交错误.json", {"request_hash": request_hash, "error": str(exc), "at": _now()})
            if task_id:
                info["task_id"] = task_id
            return _reconciliation_required(state, item_dir, info, str(exc)[:240])
    if info.get("submission_pending") and task_id:
        # A durable response identity is sufficient to resume GET, never POST.
        info.update({"submission_pending": False, "status": "SUBMITTED"})
        _write_task_info(item_dir, info)
        key = _attempt_key(item_dir)
        if key in state.budget_ledger:
            state.budget_ledger[key].update({"status": "spent", "task_id": task_id})
            state.item_failures.pop(video_id, None)
            save_state(batch_dir, state)
    polled = _poll_item(task_id, api_key)
    _record_execution(item_dir, "查询结果.json", polled)
    resumed_task_id = task_id if not submitted else ""
    if polled["status"] not in {"success", "succeeded", "completed"}:
        info = _task_info(item_dir)
        info.update({"status": str(polled["status"]).upper(), "updated_at": _now()})
        _write_task_info(item_dir, info)
        return {
            "ok": False,
            "task_id": task_id,
            "resumed_task_id": resumed_task_id,
            "status": polled["status"],
        }
    candidate = _download_item(str(polled["url"]), item_dir)
    technical = validate_video_file(
        candidate, _expected_video_resolution(batch_dir, item_dir, info)
    )
    technical.update({"version": f"V{_item_retry_count(item_dir) + 1:02d}", "task_id": task_id, "checked_at": _now()})
    _persist_video_evidence(item_dir, technical)
    info = _task_info(item_dir)
    info.update({"status": "WAITING_FINAL_REVIEW", "candidate": str(candidate.resolve()), "technical_sha256": technical["sha256"]})
    _write_task_info(item_dir, info)
    return {
        "ok": bool(technical["ok"]),
        "task_id": task_id,
        "resumed_task_id": resumed_task_id,
        "candidate": str(candidate.resolve()),
        "technical": technical,
    }


def _persist_video_evidence(item_dir: Path, evidence: dict[str, object]) -> None:
    _atomic_json(item_dir / "_工作文件/验收记录/视频技术检查.json", evidence)
    workflow = _load_workflow_cli()
    summary = "# 本地视频技术检查\n\n" + json.dumps({key: evidence.get(key) for key in ("ok", "full_decode", "duration", "width", "height", "sha256", "version")}, ensure_ascii=False) + "\n"
    workflow.atomic_write_text(item_dir / "_工作文件/验收记录/自动验收报告.md", summary)


def validate_native_4k_image(
    source: Path, output: Path, *, width: int = 2160, height: int = 3840
) -> dict[str, object]:
    source = Path(source).resolve()
    output = Path(output).resolve()
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError("生成图片结果不存在或为空")
    if width <= 0 or height <= 0:
        raise ValueError("图片目标尺寸必须为正数")
    try:
        with Image.open(source) as image:
            image.load()
            source_size = image.size
            if image.size != (width, height):
                raise ValueError(
                    f"生成图片必须为原生{width}×{height}，禁止本地放大"
                )
            normalized = image.convert("RGB")
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(output.suffix + ".tmp")
            normalized.save(temporary, format="PNG")
            temporary.replace(output)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("生成图片结果无法在本地解码") from exc
    return {
        "source_size": list(source_size),
        "source_sha256": _sha256(source),
        "source_path": str(source),
        "target_size": [width, height],
        "sha256": _sha256(output),
    }


# Backwards-compatible name for callers outside the runner.  It is now a strict
# validator; no local resize, crop, or spatial resampling occurs.
normalize_web_image = validate_native_4k_image


def accept_generated_image(
    item_dir: Path,
    artifact_name: str,
    source: Path,
    *,
    provider: str = "gpt_web",
) -> dict[str, object]:
    if artifact_name not in {"分镜图.png", "尾帧图.png", "封面图.png"}:
        raise ValueError(f"不支持的图片产出：{artifact_name}")
    item_dir = Path(item_dir).resolve()
    item_dir.mkdir(parents=True, exist_ok=True)
    workflow = _load_workflow_cli()
    candidate_name = {
        "分镜图.png": "分镜候选.png",
        "尾帧图.png": "尾帧候选.png",
        "封面图.png": "封面候选.png",
    }[artifact_name]
    candidate = item_dir / "_工作文件" / "生成过程" / candidate_name
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError("生成图片结果不存在")
    raw = candidate.parent / (candidate.stem + "_原始_" + _sha256(source)[:16] + source.suffix)
    if raw.resolve() != source:
        raw.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, raw)
    technical = validate_native_4k_image(raw, candidate)
    _atomic_json(item_dir / "_工作文件/验收记录" / (candidate.stem + "_技术检查.json"), technical)
    _atomic_json(item_dir / "_工作文件/验收记录" / (candidate.stem + "_技术检查_" + technical["source_sha256"][:16] + ".json"), technical)
    if artifact_name == "尾帧图.png":
        storyboard = workflow.validated_promoted_artifact_path(item_dir, "分镜图.png")
        if storyboard is None:
            raise ValueError("尾帧处理前必须存在已晋升分镜图")
        if _sha256(storyboard) == technical["sha256"]:
            raise ValueError("尾帧不得与分镜相同")
    if artifact_name == "分镜图.png":
        last_frame = workflow.validated_promoted_artifact_path(item_dir, "尾帧图.png")
        if last_frame is not None and _sha256(last_frame) == technical["sha256"]:
            raise ValueError("分镜不得与尾帧相同")
    event = workflow.record_artifact_decision(
        item_dir,
        artifact_name,
        candidate,
        "passed",
        "batch-auto-authorization",
        "生成图片结果按图片免审规则完成本地技术检查并自动晋升",
    )
    promoted = workflow.promote_approved_artifact(item_dir, event)
    return {
        "ok": True,
        "provider": provider,
        "review": "skipped_by_policy",
        "artifact": artifact_name,
        "path": str(promoted.resolve()),
        "sha256": technical["sha256"],
        "size": technical["target_size"],
    }


def consume_model_call(
    state: RunnerState, policy: dict[str, object], *, video_id: Optional[str]
) -> None:
    limits = policy["model_budget"]
    if not isinstance(limits, dict):
        raise ModelBudgetExceeded("模型调用预算配置无效")
    if video_id is None:
        limit = int(limits["batch_content_calls"])
        if state.model_calls_batch >= limit:
            raise ModelBudgetExceeded("批次内容模型调用预算已耗尽")
        state.model_calls_batch += 1
        return
    limit = int(limits["per_video"])
    used = state.model_calls_by_video.get(video_id, 0)
    if used >= limit:
        raise ModelBudgetExceeded(f"{video_id} 模型调用预算已耗尽")
    state.model_calls_by_video[video_id] = used + 1


def record_image_failure(
    state: RunnerState, *, video_id: str, artifact: str, reason: str, retries: int = 1
) -> dict[str, object]:
    key = f"{video_id}:{artifact}"
    failures = state.image_failures.get(key, 0) + 1
    state.image_failures[key] = failures
    if failures <= retries:
        return {
            "kind": "IMAGE_FAILURE_RECORDED",
            "retry_pending": True,
            "video_id": video_id,
            "artifact": artifact,
            "attempt": failures + 1,
            "reason": reason,
        }
    local_reason = f"{key} 图片技术重试已耗尽：{reason}"
    state.item_failures[video_id] = {"kind": "image", "reason": local_reason}
    return {"kind": "ITEM_BLOCKED", "video_id": video_id, "reason": local_reason}


def _video_items(batch_dir: Path) -> list[Path]:
    if not batch_dir.is_dir():
        return []
    return sorted(
        path for path in batch_dir.iterdir() if path.is_dir() and re.match(r"^V\d{3}_", path.name)
    )


def accept_batch_content(
    batch_dir: Path, content_dir: Path, profile_path: Path, *, video_ids: Optional[list[str]] = None
) -> dict[str, object]:
    workflow = _load_workflow_cli()
    accepted: list[str] = []
    failures: dict[str, str] = {}
    for item in _video_items(batch_dir):
        video_id = item.name.split("_", 1)[0]
        if video_ids is not None and video_id not in video_ids:
            continue
        content_path = content_dir / f"{video_id}.json"
        try:
            if not content_path.is_file():
                raise ValueError(f"缺少结构化内容：{content_path}")
            package = json.loads(content_path.read_text(encoding="utf-8"))
            if not isinstance(package, dict):
                raise ValueError("内容校验失败：content.object_required")
            if package.get("video_id") not in (None, video_id):
                raise ValueError("内容 video_id 与项目不一致")
            workflow.save_content_package(item, content_path, profile_path)
            accepted.append(video_id)
        except (OSError, ValueError, KeyError) as exc:
            failures[video_id] = str(exc)
    result = {"ok": not failures, "accepted": accepted}
    if failures:
        result["failures"] = failures
    return result


def _require_running(state: RunnerState) -> None:
    if state.status not in {"RUNNING_AUTOMATICALLY", "GENERATING"}:
        raise PermissionError("当前状态不允许执行或接收新的生成动作")


def _store_reserved_action(
    state: RunnerState, action: dict[str, object], category: str
) -> dict[str, object]:
    action = {**action, "action_id": uuid.uuid4().hex}
    state.model_actions[action["action_id"]] = {
        **action,
        "category": category,
        "status": "reserved",
        "reserved_at": _now(),
    }
    state.pending_action = action
    return action


def _reserve_action(batch: Path, state: RunnerState, policy: dict[str, object], action: dict[str, object], category: str) -> dict[str, object]:
    pending = state.pending_action or {}
    old = state.model_actions.get(pending.get("action_id"), {})
    if old.get("status") == "reserved":
        if old.get("category") == category and old.get("video_id") == action.get("video_id") and old.get("artifact") == action.get("artifact"):
            return pending
        raise ValueError("存在未接收的模型动作；必须先恢复或记录该动作失败")
    limits = policy["model_budget"]
    video_id = action.get("video_id")
    if category == "gpt_web_image":
        used = state.image_calls_by_video.get(video_id, 0)
        if used >= limits["image_calls_per_video"]:
            raise ModelBudgetExceeded(f"{video_id} GPT 网页图片次数已耗尽")
        state.image_calls_by_video[video_id] = used + 1
    elif category == "third_party_api_image":
        raise ValueError("third_party_api 图片动作必须调用 _reserve_image_api_action")
    else:
        limit_name = {"content_create": "batch_content_calls", "content_correction": "content_correction_calls", "diagnostic": "diagnostic_calls"}[category]
        used = state.model_usage.get(category, 0)
        if used >= limits[limit_name]:
            raise ModelBudgetExceeded(f"{category} 模型调用预算已耗尽")
        if video_id:
            consume_model_call(state, policy, video_id=video_id)
        state.model_usage[category] = used + 1
        if category == "content_create":
            state.model_calls_batch += 1
    action = _store_reserved_action(state, action, category)
    save_state(batch, state)
    return action


def _reserve_image_api_action(
    batch: Path, state: RunnerState, action: dict[str, object]
) -> dict[str, object]:
    pending = state.pending_action or {}
    old = state.model_actions.get(pending.get("action_id"), {})
    if old.get("status") == "reserved":
        if (
            old.get("category") == "third_party_image_api"
            and old.get("video_id") == action.get("video_id")
            and old.get("artifact") == action.get("artifact")
        ):
            return pending
        raise ValueError("存在未接收的图片 API 动作；必须先恢复或记录该动作失败")
    config = state.approved_manifest["image_api_config"]
    unit_price = _positive_authorization_amount(
        config["unit_price_yuan"], "图片 API 单价"
    )
    batch_budget = _positive_authorization_amount(
        config["batch_budget_yuan"], "图片 API 批次预算"
    )
    used = sum(
        (Decimal(row["cost"]) for row in state.image_budget_ledger.values()
         if row["status"] in {"reserved", "spent", "unknown"}),
        Decimal("0"),
    )
    if used + unit_price > batch_budget:
        raise ModelBudgetExceeded("图片 API 批次预算已耗尽")
    action = {
        **action,
        "estimated_cost_yuan": str(unit_price),
        "remaining_image_budget_yuan": str(batch_budget - used - unit_price),
    }
    action = _store_reserved_action(state, action, "third_party_image_api")
    state.image_budget_ledger[action["action_id"]] = {
        "action_id": action["action_id"],
        "provider": "third_party_api",
        "cost": str(unit_price),
        "status": "reserved",
        "at": _now(),
    }
    save_state(batch, state)
    return action


def _settle_image_api_action(
    state: RunnerState, row: dict[str, object], outcome: str
) -> None:
    if row.get("provider") != "third_party_api":
        return
    ledger = state.image_budget_ledger.get(row["action_id"])
    if ledger is None:
        raise ValueError("缺少图片 API 费用保留记录")
    target = {
        "accepted": "spent",
        "not_sent": "released",
        "sent": "spent",
        "unknown": "unknown",
    }[outcome]
    if ledger["status"] == "reserved":
        ledger["status"] = target
        ledger["settled_at"] = _now()
    elif ledger["status"] != target:
        raise ValueError("图片 API 费用动作已按不同结果结算")


def _action_receipt(
    state: RunnerState, action_id: Optional[str], expected_kind: Optional[str]
) -> dict[str, object]:
    action_id = action_id or (state.pending_action or {}).get("action_id")
    row = state.model_actions.get(action_id)
    if not isinstance(row, dict) or (
        expected_kind is not None and row.get("kind") != expected_kind
    ):
        raise ValueError("缺少匹配的已保留动作；先调用 next 并使用 action_id")
    return row


def _image_action_receipt(state: RunnerState, action_id: Optional[str]) -> dict[str, object]:
    row = _action_receipt(state, action_id, expected_kind=None)
    if row.get("kind") not in IMAGE_ACTION_KINDS:
        raise ValueError("动作不是可接收的图片生成动作")
    if row.get("provider") != state.approved_manifest.get("image_provider"):
        raise PermissionError("图片结果渠道与已批准批次不一致")
    return row


def _finish_action(state: RunnerState, row: dict[str, object], digest: str, result: dict[str, object], *, failed: bool = False) -> dict[str, object]:
    if row["status"] in {"accepted", "failed"}:
        if row.get("input_digest") != digest:
            raise ValueError("动作已接收其他结果，禁止重复覆盖")
        return row["result"]
    row.update({"status": "failed" if failed else "accepted", "input_digest": digest, "result": result, "completed_at": _now()})
    if (state.pending_action or {}).get("action_id") == row["action_id"]:
        state.pending_action = None
    return result


def _reference_paths(batch: Path, item: Path, artifact: str) -> list[str]:
    path = batch / "启动确认单.json"
    confirmation = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    products = [str(Path(p).resolve()) for p in confirmation.get("product_images", [])[:3] if Path(p).is_file()]
    refs = []
    if artifact != "分镜图.png":
        story = _load_workflow_cli().validated_promoted_artifact_path(item, "分镜图.png")
        if story is not None:
            refs.append(str(story.resolve()))
    refs.extend(products)
    if artifact == "封面图.png" and confirmation.get("cover_reference_dir"):
        folder = Path(confirmation["cover_reference_dir"])
        styles = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
        if styles:
            index = _video_items(batch).index(item)
            refs.append(str(styles[index % len(styles)].resolve()))
    return list(dict.fromkeys(refs))


def _image_action_kind(provider: str) -> str:
    return {
        "gpt_web": "GPT_WEB_IMAGE_REQUIRED",
        "third_party_api": "THIRD_PARTY_IMAGE_REQUIRED",
    }[provider]


def prepare_payload(batch: Path, item: Path, state: RunnerState) -> Path:
    validate_approved_manifest(batch, state)
    workflow = _load_workflow_cli()
    process = item / "_工作文件/生成过程"
    package = json.loads((process / "策划内容.json").read_text(encoding="utf-8"))
    prompt_contract = _load_prompt_contract()
    compiled = prompt_contract.compile_video_prompt(
        str(package["video_prompt"]),
        list(package["people"]),
        list(package["script_segments"]),
    )
    issues = prompt_contract.validate_video_request(
        compiled, list(package["script_segments"])
    )
    if issues:
        raise ValueError("视频提交提示词预检失败：" + ",".join(issues))
    key = _attempt_key(item)
    payload = {
        "prompt": compiled,
        "duration": 15,
        "resolution": {"768P": "768p竖", "2K": "2K"}[
            state.approved_manifest["resolution"]
        ],
        "seed": int(
            hashlib.sha256((state.manifest_digest + key).encode()).hexdigest()[:12],
            16,
        ),
    }
    for field, name in (("first_frame", "分镜图.png"), ("last_frame", "尾帧图.png")):
        image = workflow.validated_promoted_artifact_path(item, name)
        if image is None:
            raise ValueError(f"缺少有效首尾帧：{name}")
        payload[field] = "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode("ascii")
    path = item / "_工作文件/任务状态/提交请求.json"
    prompt_path = process / "视频提交提示词.txt"
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise PermissionError("已准备提交请求与当前内容/授权配置不一致")
        if existing.get("prompt") != compiled:
            raise PermissionError("已准备提交请求提示词与当前内容不一致")
        if prompt_path.is_file() and prompt_path.read_text(encoding="utf-8") != compiled:
            raise PermissionError("已提交提示词与已准备提交请求不一致")
        if not prompt_path.is_file():
            workflow.atomic_write_text(prompt_path, compiled)
    else:
        if prompt_path.exists():
            raise PermissionError("已有视频提交提示词但缺少提交请求；拒绝部分写入")
        _atomic_json(path, payload)
        try:
            workflow.atomic_write_text(prompt_path, compiled)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    binding = _payload_binding(batch, item, state)
    if key in state.payload_bindings and state.payload_bindings[key] != binding:
        raise PermissionError("已绑定提交请求发生变化")
    state.payload_bindings[key] = binding
    save_state(batch, state)
    return path


RECOVERABLE_ITEM_KINDS = {"preflight", "local_retry", "payload"}


def _has_submission_evidence(item: Path, state: RunnerState) -> bool:
    info = _task_info(item)
    if not all(isinstance(info.get(key), str) and info[key].strip() for key in ("task_id", "request_hash")):
        return False
    ledger = state.budget_ledger.get(_attempt_key(item))
    return ledger is None or (ledger.get("status") == "spent" and ledger.get("task_id") == info["task_id"] and ledger.get("request_hash") == info["request_hash"])


def _reviewable_items(batch: Path, state: RunnerState) -> list[Path]:
    workflow = _load_workflow_cli()
    result = []
    for item in _video_items(batch):
        if not _has_submission_evidence(item, state):
            continue
        path = item / "_工作文件/验收记录/视频技术检查.json"
        if not path.is_file():
            continue
        try:
            evidence = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(evidence, dict):
                continue
            media = workflow._review_media(batch, item, "视频.mp4")
            if (evidence.get("ok") is True and evidence.get("full_decode") is True
                    and evidence.get("version") == f"V{_item_retry_count(item) + 1:02d}"
                    and evidence.get("task_id") == _task_info(item)["task_id"]
                    and media["sha256"] and evidence.get("sha256") == media["sha256"]):
                result.append(item)
        except (OSError, ValueError):
            continue
    return result


def _open_final_review(batch: Path, state: RunnerState) -> Optional[dict[str, object]]:
    workflow = _load_workflow_cli()
    items = _reviewable_items(batch, state)
    if not any(workflow.validated_promoted_artifact_path(item, "视频.mp4") is None for item in items):
        return None
    ids = [item.name.split("_", 1)[0] for item in items]
    report = workflow.build_review_report(batch, video_ids=ids)
    action = {"kind": "USER_FINAL_REVIEW_REQUIRED", "report_path": str(report), "video_ids": ids, "blocked_items": dict(state.item_failures)}
    action["candidates"] = {item.name.split("_", 1)[0]: workflow._review_media(batch, item, "视频.mp4") for item in items}
    state.human_gate = action
    transition(state, "WAITING_FINAL_REVIEW", reason="真实视频候选已就绪；未完成项目不参加本次验收")
    save_state(batch, state)
    return action


def _local_recovery_action(state: RunnerState) -> dict[str, object]:
    ids = sorted(i for i, row in state.item_failures.items() if row.get("kind") in RECOVERABLE_ITEM_KINDS)
    return {"kind": "LOCAL_WORK_REQUIRED", "video_ids": ids, "recovery_required": True,
            "resume_command": "run-local", "failures": {i: state.item_failures[i] for i in ids}}


def next_action(
    batch_dir: Path, state: RunnerState, policy: dict[str, object]
) -> dict[str, object]:
    if state.status == "WAITING_START_APPROVAL":
        return {"kind": "USER_START_APPROVAL_REQUIRED"}
    if state.status == "BLOCKED":
        return {"kind": "BLOCKED", "reason": state.blocked_reason}
    validate_approved_manifest(batch_dir, state)
    if isinstance(state.pending_action, dict) and state.pending_action.get("action_id"):
        row = state.model_actions.get(state.pending_action["action_id"], {})
        if row.get("status") == "reserved":
            return state.pending_action
    if state.status == "WAITING_RERUN_APPROVAL":
        return state.human_gate or {"kind": "USER_RERUN_APPROVAL_REQUIRED"}
    if state.status == "WAITING_FINAL_REVIEW":
        return state.human_gate or {"kind": "USER_FINAL_REVIEW_REQUIRED", "report_path": str((batch_dir / "批次验收报告.html").resolve())}
    if state.status == "COMPLETED":
        return _finalize_outputs(batch_dir, state)
    if (state.human_gate or {}).get("kind") == "LOCAL_OUTPUT_REPAIR_REQUIRED":
        return state.human_gate
    if state.status == "WAITING_PAID_APPROVAL":
        return {"kind": "USER_START_APPROVAL_REQUIRED"}
    try:
        image_provider = _load_policy_module().normalize_image_provider(
            state.approved_manifest["image_provider"]
        )
        if image_provider == "gpt_web":
            if state.approved_manifest.get("image_api_config") != {}:
                raise ValueError("gpt_web 图片渠道不得携带第三方 API 配置")
        else:
            _load_policy_module().normalize_image_api_config(
                state.approved_manifest.get("image_api_config")
            )
    except (KeyError, ValueError) as exc:
        reason = f"启动图片渠道配置无效：{exc}"
        transition(state, "BLOCKED", reason=reason)
        save_state(batch_dir, state)
        return {"kind": "BLOCKED", "reason": reason}
    items = _video_items(batch_dir)
    workflow = _load_workflow_cli()
    missing_content = []
    local_items = []
    for item in items:
        video_id = item.name.split("_", 1)[0]
        if state.item_failures.get(video_id, {}).get("kind") not in (None, "content"):
            continue
        process = item / "_工作文件" / "生成过程"
        if not (process / "策划内容.json").is_file():
            missing_content.append(video_id)
            continue
        for artifact, prompt_name, raw_name in (
            ("分镜图.png", "分镜提示词.txt", "生图原始分镜.png"),
            ("尾帧图.png", "合理尾帧提示词.txt", "生图原始尾帧.png"),
            ("封面图.png", "封面提示词.txt", "生图原始封面.png"),
        ):
            if workflow.validated_promoted_artifact_path(item, artifact) is None:
                if not (process / prompt_name).is_file():
                    state.item_failures[video_id] = {"kind": "content", "reason": f"缺少提示词：{prompt_name}"}
                    missing_content.append(video_id)
                    break
                references = _reference_paths(batch_dir, item, artifact)
                compiled_name = {
                    "分镜图.png": "分镜提交提示词.txt",
                    "尾帧图.png": "尾帧提交提示词.txt",
                    "封面图.png": "封面提交提示词.txt",
                }[artifact]
                prompt_contract = _load_prompt_contract()
                try:
                    compiled_prompt = prompt_contract.compile_image_prompt(
                        (process / prompt_name).read_text(encoding="utf-8"),
                        artifact,
                    )
                    issues = prompt_contract.validate_image_request(
                        compiled_prompt, references, 2160, 3840
                    )
                    if issues:
                        raise ValueError(
                            "图片提交提示词预检失败：" + ",".join(issues)
                        )
                    compiled_path = process / compiled_name
                    workflow.atomic_write_text(compiled_path, compiled_prompt)
                except (OSError, ValueError) as exc:
                    reason = str(exc)
                    state.item_failures[video_id] = {"kind": "content", "reason": reason}
                    save_state(batch_dir, state)
                    return {
                        "kind": "CONTENT_PREFLIGHT_FAILED",
                        "video_id": video_id,
                        "artifact": artifact,
                        "reason": reason,
                    }
                action = {
                    "kind": _image_action_kind(image_provider),
                    "provider": image_provider,
                    "video_id": video_id,
                    "artifact": artifact,
                    "prompt_path": str(compiled_path.resolve()),
                    "output_path": str((process / raw_name).resolve()),
                    "reference_paths": references,
                    "attempt": state.image_failures.get(f"{video_id}:{artifact}", 0) + 1,
                    "width": 2160,
                    "height": 3840,
                    "size": "2160x3840",
                    "native_resolution_required": True,
                }
                if image_provider == "third_party_api":
                    action["api_config"] = dict(
                        state.approved_manifest["image_api_config"]
                    )
                    action["request_parameters"] = {"width": 2160, "height": 3840}
                try:
                    if image_provider == "third_party_api":
                        return _reserve_image_api_action(batch_dir, state, action)
                    return _reserve_action(
                        batch_dir, state, policy, action, "gpt_web_image"
                    )
                except ModelBudgetExceeded as exc:
                    state.item_failures[video_id] = {"kind": "image", "reason": str(exc)}
                    break
        else:
            if not _video_complete(item, state):
                local_items.append(video_id)
    if missing_content:
        category = "content_create" if not state.model_usage.get("content_create") else "content_correction"
        prompt_path = batch_dir / "_批次内容/内容任务.json"
        output = prompt_path.parent
        _atomic_json(prompt_path, {"video_ids": missing_content, "tasks": [{"video_id": i, "selling_point": _task_info(_find_item_dir(batch_dir, i)).get("selling_point"), "validation_errors": state.item_failures.get(i)} for i in missing_content], "content_contract": str((Path(__file__).resolve().parents[1] / "references/content-contract.md").resolve())})
        action = {"kind": "BATCH_CONTENT_REQUIRED", "purpose": category, "video_ids": missing_content, "output_dir": str(output.resolve()), "prompt_path": str(prompt_path.resolve())}
        try:
            return _reserve_action(batch_dir, state, policy, action, category)
        except ModelBudgetExceeded as exc:
            for i in missing_content:
                state.item_failures[i] = {"kind": "content_budget", "reason": str(exc)}
    if local_items:
        for i in local_items:
            try:
                prepare_payload(batch_dir, _find_item_dir(batch_dir, i), state)
            except (OSError, ValueError, PermissionError) as exc:
                state.item_failures[i] = {"kind": "payload", "reason": str(exc)}
        local_items = [i for i in local_items if i not in state.item_failures]
        if local_items:
            save_state(batch_dir, state)
            return {"kind": "LOCAL_WORK_REQUIRED", "video_ids": local_items}
    review = _open_final_review(batch_dir, state)
    if review is not None:
        return review
    if any(row.get("kind") in RECOVERABLE_ITEM_KINDS for row in state.item_failures.values()):
        save_state(batch_dir, state)
        return _local_recovery_action(state)
    if (state.human_gate or {}).get("kind") == "USER_RERUN_APPROVAL_REQUIRED":
        transition(state, "WAITING_RERUN_APPROVAL", reason="仍有 V01 等待逐项重跑授权")
        save_state(batch_dir, state)
        return state.human_gate
    reason = "没有可自动执行的项目；" + "; ".join(f"{i}: {row['reason']}" for i, row in state.item_failures.items())
    transition(state, "BLOCKED", reason=reason)
    save_state(batch_dir, state)
    return {"kind": "BLOCKED", "reason": reason}


def _video_complete(item: Path, state: RunnerState) -> bool:
    marker = "video:" + _attempt_key(item).split(":")[1]
    return marker in state.completed_nodes.get(item.name.split("_", 1)[0], [])


def _item_retry_count(item_dir: Path) -> int:
    raw = _task_info(item_dir).get("retry_count", 0)
    try:
        parsed = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{item_dir.name} 的视频版本状态无效") from exc
    if (
        not parsed.is_finite()
        or parsed != parsed.to_integral_value()
        or int(parsed) not in {0, 1}
    ):
        raise ValueError(f"{item_dir.name} 的视频版本状态无效")
    return int(parsed)


def _route_video_failures(
    batch_dir: Path,
    state: RunnerState,
    failures: dict[str, str],
) -> dict[str, object]:
    rerunnable: list[str] = []
    terminal: list[str] = []
    for video_id in sorted(failures):
        item = _find_item_dir(batch_dir, video_id)
        if not _has_submission_evidence(item, state):
            state.item_failures[video_id] = {"kind": "preflight", "reason": failures[video_id]}
            info = _task_info(item)
            info.update({"status": "PREFLIGHT_REQUIRED", "failure_reason": failures[video_id]})
            _write_task_info(item, info)
            continue
        state.item_failures[video_id] = {"kind": "video", "reason": failures[video_id]}
        info = _task_info(item)
        info.update({"status": "VIDEO_FAILED", "failure_reason": failures[video_id]})
        _write_task_info(item, info)
        if _item_retry_count(item) == 0:
            rerunnable.append(video_id)
        else:
            terminal.append(video_id)

    if rerunnable:
        action: dict[str, object] = {
            "kind": "USER_RERUN_APPROVAL_REQUIRED",
            "video_ids": rerunnable,
            "failures": [
                {"video_id": video_id, "reason": failures[video_id]}
                for video_id in rerunnable
            ],
        }
        if terminal:
            action["non_rerunnable_video_ids"] = terminal
        state.human_gate = action
        transition(
            state,
            "WAITING_RERUN_APPROVAL",
            reason=f"V01 失败，等待 V02 授权：{','.join(rerunnable)}",
        )
        save_state(batch_dir, state)
        return action

    if not terminal:
        transition(state, "RUNNING_AUTOMATICALLY", reason="未提交项目保留原版本，修复本地环境后继续")
        save_state(batch_dir, state)
        return _local_recovery_action(state)
    reason = f"V02 已失败且禁止再次重跑：{','.join(terminal)}"
    state.human_gate = {
        "kind": "BLOCKED",
        "video_ids": terminal,
        "failures": [
            {"video_id": video_id, "reason": failures[video_id]}
            for video_id in terminal
        ],
    }
    transition(state, "BLOCKED", reason=reason)
    save_state(batch_dir, state)
    return {"kind": "BLOCKED", "reason": reason, "video_ids": terminal}


def _failed_review_items(result_path: Path) -> dict[str, str]:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    failures: dict[str, str] = {}
    for item in result.get("items", []):
        if isinstance(item, dict) and item.get("decision") == "failed":
            video_id = str(item.get("video_id") or "")
            if video_id:
                failures[video_id] = str(item.get("reason") or "用户最终验收不通过")
    return failures


def _promote_passed_candidate(
    workflow: object,
    item_dir: Path,
    artifact_name: str,
    source_path: Path,
    *,
    confirmed_by: str,
    feedback: str,
    expected_sha256: str = "",
) -> Path:
    promoted = workflow.validated_promoted_artifact_path(item_dir, artifact_name)
    if promoted is not None:
        if expected_sha256 and _sha256(promoted) != expected_sha256:
            raise ValueError(f"{artifact_name} 已晋升产出与验收哈希不一致")
        return promoted

    source_path = source_path if source_path.is_absolute() else item_dir / source_path
    source_path = source_path.resolve()
    if not source_path.is_file():
        raise ValueError(f"{artifact_name} 候选不存在：{source_path}")
    digest = _sha256(source_path)
    if expected_sha256 and digest != expected_sha256:
        raise ValueError(f"{artifact_name} 候选哈希与验收结果不一致")
    events = workflow.load_approval_events(item_dir)
    event = workflow.latest_artifact_decision(events, artifact_name, digest)
    if event is None or event.get("decision") != "passed":
        event = workflow.record_artifact_decision(
            item_dir,
            artifact_name,
            source_path,
            "passed",
            confirmed_by,
            feedback,
        )
    if expected_sha256 and event.get("sha256") != expected_sha256:
        raise ValueError(f"{artifact_name} 验收快照与技术检查哈希不一致")
    return workflow.promote_approved_artifact(item_dir, event)


def _promote_passed_review_outputs(
    batch_dir: Path, result_path: Path, workflow: object
) -> None:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    for decision in result.get("items", []):
        if not isinstance(decision, dict):
            raise ValueError("最终验收项目记录必须为对象")
        video_id = str(decision.get("video_id") or "")
        item_dir = _find_item_dir(batch_dir, video_id)
        process = item_dir / "_工作文件" / "生成过程"
        for artifact_name in ("标题.txt", "发布正文.txt", "话题标签.txt"):
            try:
                _promote_passed_candidate(
                    workflow,
                    item_dir,
                    artifact_name,
                    process / artifact_name,
                    confirmed_by="batch-auto-authorization",
                    feedback="结构化内容契约通过后按批次自动执行授权晋升",
                )
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                raise ValueError(
                    f"{video_id} 非视频产出晋升失败（{artifact_name}）：{exc}"
                ) from exc

        if decision.get("decision") != "passed":
            continue
        artifacts = decision.get("artifacts")
        video = artifacts.get("视频.mp4") if isinstance(artifacts, dict) else None
        if not isinstance(video, dict):
            raise ValueError(f"{video_id} 视频验收结果缺少候选证据")
        source_path = str(video.get("source_path") or "").strip()
        expected_sha256 = str(video.get("sha256") or "").strip().lower()
        if not source_path or not expected_sha256:
            raise ValueError(f"{video_id} 视频验收结果缺少候选路径或 SHA-256")
        evidence_path = item_dir / "_工作文件/验收记录/视频技术检查.json"
        if not evidence_path.is_file():
            raise ValueError(f"{video_id} 缺少候选绑定的全片技术检查证据")
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        if (evidence.get("ok") is not True or evidence.get("full_decode") is not True
                or evidence.get("sha256") != expected_sha256
                or evidence.get("version") != f"V{_item_retry_count(item_dir) + 1:02d}"):
            raise ValueError(f"{video_id} 技术检查证据与当前候选哈希/版本不一致")
        source = Path(source_path)
        source = source if source.is_absolute() else item_dir / source
        promoted = workflow.validated_promoted_artifact_path(item_dir, "视频.mp4")
        approved_alias = promoted is not None and source.resolve() == promoted.resolve() and _sha256(promoted) == expected_sha256
        if source.resolve() != Path(str(evidence.get("candidate", ""))).resolve() and not approved_alias:
            raise ValueError(f"{video_id} 技术检查证据与验收候选路径不一致")
        try:
            _promote_passed_candidate(
                workflow,
                item_dir,
                "视频.mp4",
                Path(source_path),
                confirmed_by="user-final-review",
                feedback="用户最终验收明确通过",
                expected_sha256=expected_sha256,
            )
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            raise ValueError(f"{video_id} 视频产出晋升失败：{exc}") from exc


def _audit_problem_summary(item: dict[str, object]) -> str:
    problems: list[str] = []
    for key in ("errors", "missing", "demoted"):
        values = item.get(key, [])
        if not isinstance(values, list):
            problems.append(f"{key}=invalid")
            continue
        if not values:
            continue
        names: list[str] = []
        for value in values:
            if isinstance(value, dict):
                label = value.get("artifact_name") or value.get("error") or "unknown"
                names.append(str(label))
            else:
                names.append(str(value))
        problems.append(f"{key}={','.join(names)}")
    valid = item.get("valid")
    if not isinstance(valid, list):
        problems.append("valid=missing")
    elif len(valid) != 7:
        problems.append(f"valid_count={len(valid)}/7")
    return ";".join(problems)


def _audit_problem_scope(item: dict[str, object]) -> tuple[set[str], bool]:
    artifacts: set[str] = set()
    unknown = False
    explicit_problem = False
    for key in ("errors", "missing", "demoted"):
        values = item.get(key, [])
        if not isinstance(values, list):
            unknown = True
            continue
        for value in values:
            explicit_problem = True
            if isinstance(value, dict):
                artifact_name = str(value.get("artifact_name") or "")
            elif key == "missing":
                artifact_name = str(value)
            else:
                artifact_name = ""
            if artifact_name:
                artifacts.add(artifact_name)
            else:
                unknown = True
    valid = item.get("valid")
    valid_problem = not isinstance(valid, list) or len(valid) != 7
    if valid_problem and not explicit_problem:
        unknown = True
    return artifacts, unknown


def _finalize_outputs(batch: Path, state: RunnerState) -> dict[str, object]:
    """The only DONE gate: freshly audit the entire batch, never just reviewed IDs."""
    workflow = _load_workflow_cli()
    items = {item.name.split("_", 1)[0]: item for item in _video_items(batch)}
    expected = set(state.approved_manifest.get("video_ids", items))
    try:
        audit = workflow.audit_batch_outputs(batch)
    except (OSError, ValueError, RuntimeError) as exc:
        audit = {"items": [], "errors": [{"error": str(exc)}]}
    audit.update({"checked_at": _now(), "expected_video_ids": sorted(expected)})
    rows = {Path(row["item_dir"]).name.split("_", 1)[0]: row for row in audit.get("items", [])}
    problems = {}
    for video_id in sorted(expected | set(items)):
        row = rows.get(video_id)
        if row is None:
            row = {"item_dir": str(items.get(video_id, "")), "valid": [], "missing": sorted(workflow.DELIVERABLE_NAMES), "errors": [{"error": "批准项目缺少完整交付审计记录"}], "demoted": []}
        else:
            row = dict(row)
            actual_names = {value.get("artifact_name") for value in row.get("valid", [])}
            errors = list(row.get("errors", []))
            if not _audit_problem_summary(row) and actual_names != set(workflow.DELIVERABLE_NAMES):
                errors.append({"error": "审计结果未完整覆盖七项最终产出"})
            if video_id not in expected:
                errors.append({"error": "实际项目不在批准清单中"})
            row["errors"] = errors
        if audit.get("errors"):
            row["errors"] = [*row.get("errors", []), *audit["errors"]]
        if video_id in items and _task_info(items[video_id]).get("status") not in {"COMPLETED", "OUTPUT_REPAIR_REQUIRED"}:
            row["errors"] = [*row.get("errors", []), {"error": "项目尚无最终验收完成记录"}]
        if _audit_problem_summary(row):
            problems[video_id] = {key: row.get(key, []) for key in ("missing", "demoted", "errors")}
            problems[video_id]["valid_count"] = len(row.get("valid", []))
    # Preserve every audit, including demotion evidence that later checks no longer see.
    audit_path = batch / "_交付审计" / (uuid.uuid4().hex + ".json")
    _atomic_json(audit_path, audit)
    _atomic_json(batch / "批次交付审计.json", {**audit, "evidence_path": str(audit_path.resolve())})
    for video_id, item in items.items():
        info = _task_info(item)
        if video_id in problems:
            reason = "整批最终交付审计未通过：" + json.dumps(problems[video_id], ensure_ascii=False, separators=(",", ":"))
            state.item_failures[video_id] = {"kind": "output_repair", "reason": reason, "audit_path": str(audit_path.resolve())}
            info.update({"status": "OUTPUT_REPAIR_REQUIRED", "failure_reason": reason})
        elif state.item_failures.get(video_id, {}).get("kind") == "output_repair":
            state.item_failures.pop(video_id)
            info.update({"status": "COMPLETED", "completed_at": _now()})
            info.pop("failure_reason", None)
        _write_task_info(item, info)
        _record_execution(item, "最终交付审计.json", {"audit_path": str(audit_path.resolve()), "checked_at": audit["checked_at"], "issues": problems.get(video_id, {}), "ok": video_id not in problems})
    if problems or not expected:
        action = {"kind": "LOCAL_OUTPUT_REPAIR_REQUIRED", "video_ids": sorted(problems),
                  "items": problems, "audit_path": str(audit_path.resolve()),
                  "paid_generation_allowed": False, "resume_command": "run-local"}
        state.human_gate = action
        transition(state, "RUNNING_AUTOMATICALLY", reason="最终产出需本地恢复，禁止借此重新生成或 V02")
        save_state(batch, state)
        return action
    state.human_gate = None
    transition(state, "COMPLETED", reason="新鲜整批七项最终产出审计全部通过")
    save_state(batch, state)
    return {"kind": "DONE"}


def _failed_audit_items(
    batch_dir: Path, audit: dict[str, object], video_ids: Optional[list[str]] = None
) -> dict[str, str]:
    failures: dict[str, str] = {}
    if audit.get("errors"):
        raise ValueError("最终七项产出审计失败且无法定位视频项目：批次级错误")
    items = audit.get("items", [])
    if not isinstance(items, list):
        raise ValueError("最终七项产出审计结果无效：items 必须为列表")
    expected = {
        item.name.split("_", 1)[0]: item.resolve() for item in _video_items(batch_dir)
        if video_ids is None or item.name.split("_", 1)[0] in video_ids
    }
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("最终七项产出审计结果无效：项目记录必须为对象")
        raw_item_dir = str(item.get("item_dir") or "").strip()
        problem = _audit_problem_summary(item)
        if not raw_item_dir:
            if problem:
                raise ValueError("最终七项产出审计失败且无法定位视频项目")
            raise ValueError("最终七项产出审计结果无效：缺少 item_dir")
        item_dir = Path(raw_item_dir).resolve()
        video_id = item_dir.name.split("_", 1)[0]
        if video_id not in expected or item_dir != expected[video_id]:
            raise ValueError(f"最终七项产出审计指向未知视频项目：{raw_item_dir}")
        if video_id in seen:
            raise ValueError(f"最终七项产出审计包含重复项目：{video_id}")
        seen.add(video_id)
        if problem:
            artifact_names, unknown_scope = _audit_problem_scope(item)
            if unknown_scope or any(name != "视频.mp4" for name in artifact_names):
                raise ValueError(
                    f"{video_id} 非视频产出审计失败或问题范围不明确：{problem}"
                )
            failures[video_id] = f"最终七项产出审计失败：{problem}"
    missing_items = sorted(set(expected) - seen)
    if missing_items:
        raise ValueError(
            f"最终七项产出审计项目不完整：{','.join(missing_items)}"
        )
    return failures


def run_local_until_gate(
    batch_dir: Path,
    state: RunnerState,
    policy: dict[str, object],
    *,
    dry_run: bool = False,
) -> dict[str, object]:
    if dry_run:
        previews = []
        for item in _video_items(batch_dir):
            try:
                result = run_autodl_item(batch_dir, item, state, dry_run=True)
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                result = {"ok": False, "dry_run": True, "reason": str(exc)}
            previews.append({"video_id": item.name.split("_", 1)[0], **result})
        return {"kind": "DRY_RUN_COMPLETE", "paid_calls": 0, "items": previews}
    if state.status not in {"RUNNING_AUTOMATICALLY", "GENERATING"}:
        if state.status in {"WAITING_FINAL_REVIEW", "WAITING_RERUN_APPROVAL"} and any(row.get("kind") in RECOVERABLE_ITEM_KINDS for row in state.item_failures.values()):
            transition(state, "RUNNING_AUTOMATICALLY", reason="恢复尚未完成的本地任务")
            save_state(batch_dir, state)
        else:
            return next_action(batch_dir, state, policy)
    if (state.pending_action or {}).get("action_id") and state.model_actions.get(state.pending_action["action_id"], {}).get("status") == "reserved":
        return state.pending_action
    if (state.human_gate or {}).get("kind") == "LOCAL_OUTPUT_REPAIR_REQUIRED":
        # Delivery repair never enters payload preparation, POST, polling or download.
        return _finalize_outputs(batch_dir, state)
    items = _video_items(batch_dir)
    if not items:
        return next_action(batch_dir, state, policy)
    workflow = _load_workflow_cli()
    failures: dict[str, str] = {i: row["reason"] for i, row in state.item_failures.items() if row.get("kind") == "video"}
    polling: list[str] = []
    missing: list[str] = []
    for item in items:
        video_id = item.name.split("_", 1)[0]
        if _video_complete(item, state):
            continue
        problem = state.item_failures.get(video_id, {})
        if problem.get("kind") not in {None, *RECOVERABLE_ITEM_KINDS}:
            continue
        required = ("分镜图.png", "尾帧图.png", "封面图.png")
        if not all(
            workflow.validated_promoted_artifact_path(item, artifact) is not None
            for artifact in required
        ):
            missing.append(video_id)
            continue
        try:
            prepare_payload(batch_dir, item, state)
            result = run_autodl_item(batch_dir, item, state, dry_run=False)
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            kind = "local_retry" if _task_info(item).get("task_id") else "preflight"
            state.item_failures[video_id] = {"kind": kind, "reason": str(exc)}
            info = _task_info(item)
            info.update({"status": kind.upper() + "_REQUIRED", "failure_reason": str(exc)})
            _write_task_info(item, info)
            _record_execution(item, "执行错误.json", {"stage": kind, "reason": str(exc), "at": _now()})
            save_state(batch_dir, state)
            continue
        if not result.get("ok"):
            if (
                state.status == "BLOCKED"
                or result.get("status") == "RECONCILIATION_REQUIRED"
            ):
                reason = state.blocked_reason or str(
                    result.get("reason", "付费提交状态需要人工核对")
                )
                state.item_failures[video_id] = {"kind": "reconciliation", "reason": reason}
                save_state(batch_dir, state)
                continue
            if result.get("status") == "poll_timeout" and result.get("task_id"):
                state.item_failures.pop(video_id, None)
                polling.append(video_id)
                continue
            reason = state.blocked_reason or str(result.get("status", "视频执行失败"))
            failures[video_id] = str(result.get("reason") or reason)
            state.item_failures[video_id] = {"kind": "video", "reason": failures[video_id]}
            save_state(batch_dir, state)
            continue
        candidate = Path(str(result.get("candidate") or ""))
        technical = result.get("technical", {})
        if (not candidate.is_file() or technical.get("ok") is not True
                or technical.get("full_decode") is not True or technical.get("sha256") != _sha256(candidate)):
            state.item_failures[video_id] = {"kind": "local_retry", "reason": "缺少候选绑定的全片解码技术证据"}
            save_state(batch_dir, state)
            continue
        technical.update({"candidate": str(candidate.resolve()), "version": f"V{_item_retry_count(item) + 1:02d}", "task_id": result.get("task_id") or _task_info(item).get("task_id")})
        _persist_video_evidence(item, technical)
        info = _task_info(item)
        info.update({"status": "WAITING_FINAL_REVIEW", "technical_sha256": technical["sha256"], "candidate": str(candidate.resolve())})
        _write_task_info(item, info)
        state.item_failures.pop(video_id, None)
        completed = state.completed_nodes.setdefault(video_id, [])
        marker = "video:" + _attempt_key(item).split(":")[1]
        if marker not in completed:
            completed.append(marker)
        save_state(batch_dir, state)
    if failures:
        return _route_video_failures(batch_dir, state, failures)
    if polling:
        action = {"kind": "VIDEO_POLL_PENDING", "video_ids": polling}
        state.pending_action = action
        transition(state, "GENERATING", reason=f"继续轮询：{','.join(polling)}")
        save_state(batch_dir, state)
        return action
    if missing:
        return next_action(batch_dir, state, policy)
    if not (state.pending_action or {}).get("action_id"):
        state.pending_action = None
    review = _open_final_review(batch_dir, state)
    if review is not None:
        return review
    if any(row.get("kind") in RECOVERABLE_ITEM_KINDS for row in state.item_failures.values()):
        save_state(batch_dir, state)
        return _local_recovery_action(state)
    action = {"kind": "ITEMS_BLOCKED", "items": state.item_failures}
    save_state(batch_dir, state)
    return action


def _find_item_dir(batch_dir: Path, video_id: str) -> Path:
    matches = [
        path
        for path in _video_items(batch_dir)
        if path.name.split("_", 1)[0] == video_id
    ]
    if len(matches) != 1:
        raise ValueError(f"无法唯一定位视频项目：{video_id}")
    return matches[0]


def _print_compact(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="产品视频低成本自动化状态机")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "next"):
        command = sub.add_parser(name)
        command.add_argument("--batch", type=Path, required=True)
    local = sub.add_parser("run-local")
    local.add_argument("--batch", type=Path, required=True)
    local.add_argument("--dry-run", action="store_true")
    approve = sub.add_parser("approve-start")
    approve.add_argument("--batch", type=Path, required=True)
    approve.add_argument("--approved-budget", required=True)
    approve.add_argument("--estimated-v01-total", required=True)
    approve.add_argument(
        "--image-provider",
        choices=("gpt_web", "third_party_api"),
        required=True,
    )
    approve.add_argument("--image-api-config", type=Path)
    content = sub.add_parser("accept-content")
    content.add_argument("--batch", type=Path, required=True)
    content.add_argument("--content-dir", type=Path, required=True)
    content.add_argument("--profile", type=Path, required=True)
    content.add_argument("--action-id")
    image = sub.add_parser("accept-image")
    image.add_argument("--batch", type=Path, required=True)
    image.add_argument("--video-id", required=True)
    image.add_argument(
        "--artifact",
        choices=("分镜图.png", "尾帧图.png", "封面图.png"),
        required=True,
    )
    image.add_argument("--source", type=Path, required=True)
    image.add_argument("--action-id")
    image_failed = sub.add_parser("image-failed")
    image_failed.add_argument("--batch", type=Path, required=True)
    image_failed.add_argument("--video-id", required=True)
    image_failed.add_argument(
        "--artifact",
        choices=("分镜图.png", "尾帧图.png", "封面图.png"),
        required=True,
    )
    image_failed.add_argument("--reason", required=True)
    image_failed.add_argument("--action-id")
    image_failed.add_argument(
        "--submission-state",
        choices=("not_sent", "sent", "unknown"),
        default="unknown",
    )
    rerun = sub.add_parser("approve-rerun")
    rerun.add_argument("--batch", type=Path, required=True)
    rerun.add_argument("--video-id", required=True)
    rerun.add_argument("--approved-cost", required=True)
    review = sub.add_parser("complete-review")
    review.add_argument("--batch", type=Path, required=True)
    review.add_argument("--result", type=Path, required=True)
    review.add_argument(
        "--knowledge-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data",
    )
    diagnostic = sub.add_parser("reserve-diagnostic", help="为必要异常分析保留一次模型调用")
    diagnostic.add_argument("--batch", type=Path, required=True)
    diagnostic.add_argument("--video-id", required=True)
    diagnostic.add_argument("--reason", required=True)
    accept_diagnostic = sub.add_parser("accept-diagnostic", help="接收诊断报告，不自动授权重跑")
    accept_diagnostic.add_argument("--batch", type=Path, required=True)
    accept_diagnostic.add_argument("--action-id", required=True)
    accept_diagnostic.add_argument("--result", type=Path, required=True)
    return parser


def _main_locked(args) -> int:
    try:
        skill_root = Path(__file__).resolve().parents[1]
        policy = _load_policy_module().load_policy(skill_root)
        batch = args.batch.resolve()
        if args.command == "run-local" and args.dry_run and not _state_path(batch).exists():
            state = RunnerState.new(_load_policy_module().policy_digest(policy))
        else:
            state = load_or_create_state(batch, policy)
        if args.command == "status":
            result = {"status": state.status, "pending_action": state.pending_action}
        elif args.command == "next":
            result = next_action(batch, state, policy)
        elif args.command == "approve-start":
            if state.status != "WAITING_START_APPROVAL":
                raise ValueError("当前状态不允许重复批准启动")
            approved = _positive_authorization_amount(
                args.approved_budget, "V01 批准预算"
            )
            estimated = _positive_authorization_amount(
                args.estimated_v01_total, "V01 预计总价"
            )
            if estimated > approved:
                raise ValueError("V01 预计总价必须不超过批准预算")
            confirmation_path = batch / "启动确认单.json"
            if not confirmation_path.is_file():
                raise PermissionError("缺少启动确认单和费用清单")
            confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
            image_provider, image_api_config = _approved_image_config(
                confirmation, args.image_provider, args.image_api_config
            )
            manifest = _confirmation_manifest(batch)
            if (
                manifest["image_provider"] != image_provider
                or manifest["image_api_config"] != image_api_config
            ):
                raise PermissionError("图片渠道配置与启动确认单不一致")
            if estimated != Decimal(str(manifest["estimated_v01_total"])):
                raise PermissionError("V01 预计总价与逐条费用清单不一致")
            if approved > Decimal(str(manifest["max_budget_yuan"])):
                raise PermissionError("批准预算超过启动确认单最高预算")
            state.approved_budget = str(approved)
            state.estimated_v01_total = str(estimated)
            state.approved_manifest = manifest
            state.manifest_digest = _load_policy_module().policy_digest(manifest)
            transition(state, "RUNNING_AUTOMATICALLY", reason="V01 总预算已确认")
            save_state(batch, state)
            result = next_action(batch, state, policy)
        elif args.command == "accept-content":
            _require_running(state)
            row = _action_receipt(state, args.action_id, "BATCH_CONTENT_REQUIRED")
            parts = []
            for video_id in row["video_ids"]:
                path = args.content_dir.resolve() / (video_id + ".json")
                parts.append(video_id + ":" + (_sha256(path) if path.is_file() else "missing"))
            digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
            if row["status"] != "reserved":
                result = _finish_action(state, row, digest, {})
            else:
                result = accept_batch_content(batch, args.content_dir.resolve(), args.profile.resolve(), video_ids=row["video_ids"])
                state.profile_path = str(args.profile.resolve())
                for video_id in result["accepted"]:
                    state.item_failures.pop(video_id, None)
                    nodes = state.completed_nodes.setdefault(video_id, [])
                    if "content" not in nodes:
                        nodes.append("content")
                for video_id, reason in result.get("failures", {}).items():
                    state.item_failures[video_id] = {"kind": "content", "reason": reason}
                result = _finish_action(state, row, digest, result, failed=not result["ok"])
            save_state(batch, state)
        elif args.command == "accept-image":
            existing = state.model_actions.get(
                args.action_id or (state.pending_action or {}).get("action_id")
            )
            if state.status not in {"RUNNING_AUTOMATICALLY", "GENERATING"} and (
                not isinstance(existing, dict) or existing.get("status") == "reserved"
            ):
                _require_running(state)
            validate_approved_manifest(batch, state)
            item = _find_item_dir(batch, args.video_id)
            row = _image_action_receipt(state, args.action_id)
            if row.get("video_id") != args.video_id or row.get("artifact") != args.artifact:
                raise ValueError("图片结果与已保留动作不一致")
            digest = _sha256(args.source) if args.source.is_file() else "missing"
            if row["status"] != "reserved":
                result = _finish_action(state, row, digest, {})
            else:
                _require_running(state)
                try:
                    result = accept_generated_image(
                        item, args.artifact, args.source, provider=str(row["provider"])
                    )
                except (OSError, ValueError, RuntimeError) as exc:
                    result = record_image_failure(state, video_id=args.video_id, artifact=args.artifact, reason=str(exc), retries=policy["image"]["download_retries"])
                    _settle_image_api_action(state, row, "sent")
                    _finish_action(state, row, digest, result, failed=True)
                else:
                    _settle_image_api_action(state, row, "accepted")
                    _finish_action(state, row, digest, result)
            save_state(batch, state)
        elif args.command == "image-failed":
            existing = state.model_actions.get(
                args.action_id or (state.pending_action or {}).get("action_id")
            )
            if state.status not in {"RUNNING_AUTOMATICALLY", "GENERATING"} and (
                not isinstance(existing, dict) or existing.get("status") == "reserved"
            ):
                _require_running(state)
            validate_approved_manifest(batch, state)
            _find_item_dir(batch, args.video_id)
            row = _image_action_receipt(state, args.action_id)
            if row.get("video_id") != args.video_id or row.get("artifact") != args.artifact:
                raise ValueError("图片失败与已保留动作不一致")
            if row.get("provider") == "third_party_api":
                digest = hashlib.sha256(json.dumps(
                    {"reason": args.reason, "submission_state": args.submission_state},
                    ensure_ascii=False, sort_keys=True,
                ).encode()).hexdigest()
            else:
                digest = hashlib.sha256(args.reason.encode()).hexdigest()
            if row["status"] != "reserved":
                result = _finish_action(state, row, digest, {})
            else:
                _require_running(state)
                result = record_image_failure(state, video_id=args.video_id, artifact=args.artifact, reason=args.reason, retries=policy["image"]["download_retries"])
                _settle_image_api_action(state, row, args.submission_state)
                _finish_action(state, row, digest, result, failed=True)
                if row.get("provider") == "third_party_api" and args.submission_state == "unknown":
                    transition(
                        state,
                        "BLOCKED",
                        reason="图片 API 提交状态未知，已停止自动重提",
                    )
            save_state(batch, state)
        elif args.command == "run-local":
            result = run_local_until_gate(batch, state, policy, dry_run=args.dry_run)
        elif args.command == "reserve-diagnostic":
            if state.status in {"WAITING_START_APPROVAL", "WAITING_PAID_APPROVAL", "COMPLETED"}:
                raise PermissionError("当前状态不允许保留诊断动作")
            item = _find_item_dir(batch, args.video_id)
            prompt = item / "_工作文件/任务状态/诊断任务.json"
            _atomic_json(prompt, {"reason": args.reason, "item_failure": state.item_failures.get(args.video_id), "task_info_path": str((item / "_工作文件/任务状态/任务信息.json").resolve()), "constraints": "仅分析原因和本地修复建议，不提交付费任务，不重新生图"})
            result = _reserve_action(batch, state, policy, {"kind": "MODEL_DIAGNOSTIC_REQUIRED", "video_id": args.video_id, "prompt_path": str(prompt.resolve()), "output_path": str((item / "_工作文件/任务状态/诊断结果.json").resolve())}, "diagnostic")
        elif args.command == "accept-diagnostic":
            row = _action_receipt(state, args.action_id, "MODEL_DIAGNOSTIC_REQUIRED")
            value = json.loads(args.result.read_text(encoding="utf-8"))
            digest = _load_policy_module().policy_digest(value)
            if row["status"] == "reserved":
                if not isinstance(value, dict) or not str(value.get("summary", "")).strip():
                    raise ValueError("诊断结果必须是包含 summary 的对象")
                _atomic_json(Path(row["output_path"]), value)
            result = _finish_action(state, row, digest, {"ok": True, "diagnostic_path": row["output_path"]})
            save_state(batch, state)
        elif args.command == "approve-rerun":
            if state.status != "WAITING_RERUN_APPROVAL":
                raise ValueError("当前状态不允许批准 V02 重跑")
            pending_ids = (
                state.human_gate.get("video_ids", [])
                if isinstance(state.human_gate, dict)
                else []
            )
            if args.video_id not in pending_ids:
                raise ValueError(f"{args.video_id} 不在待批准 V02 的失败项目中")
            rerun_cost = _positive_authorization_amount(
                args.approved_cost, "V02 批准费用"
            )
            validate_approved_manifest(batch, state)
            if rerun_cost != Decimal(state.approved_manifest["price_by_video"][args.video_id]):
                raise PermissionError("V02 授权金额必须与该视频预计费用完全一致")
            workflow = _load_workflow_cli()
            item = _find_item_dir(batch, args.video_id)
            if _item_retry_count(item) != 0 or not _has_submission_evidence(item, state):
                raise PermissionError("V02 需要可核对的真实 V01 提交证据；未提交项目必须继续 V01")
            _archive_v01_for_rerun(item)
            workflow.start_rerun(batch, args.video_id)
            state.rerun_budget_by_video[args.video_id] = str(rerun_cost)
            state.completed_nodes[args.video_id] = [n for n in state.completed_nodes.get(args.video_id, []) if n != "video" and not n.startswith("video:")]
            state.item_failures.pop(args.video_id, None)
            remaining = [i for i in pending_ids if i != args.video_id]
            state.human_gate = {**state.human_gate, "video_ids": remaining, "failures": [row for row in state.human_gate.get("failures", []) if row.get("video_id") in remaining]} if remaining else None
            transition(
                state,
                "RUNNING_AUTOMATICALLY",
                reason=f"{args.video_id} V02 已获授权",
            )
            save_state(batch, state)
            result = next_action(batch, state, policy)
        elif args.command == "complete-review":
            if state.status != "WAITING_FINAL_REVIEW":
                raise ValueError("当前状态不允许完成最终验收")
            workflow = _load_workflow_cli()
            reviewable = {item.name.split("_", 1)[0] for item in _reviewable_items(batch, state)}
            expected_ids = set((state.human_gate or {}).get("video_ids", reviewable))
            value = json.loads(args.result.read_text(encoding="utf-8"))
            decisions = value.get("items") if isinstance(value, dict) else None
            if not isinstance(decisions, list) or any(not isinstance(row, dict) for row in decisions):
                raise ValueError("最终验收结果必须包含项目对象列表")
            supplied_ids = [row.get("video_id") for row in decisions]
            if (any(not isinstance(i, str) for i in supplied_ids) or len(set(supplied_ids)) != len(supplied_ids)
                    or not expected_ids or set(supplied_ids) != expected_ids or not expected_ids <= reviewable):
                raise ValueError("最终验收仅允许本次报告中具有真实提交和匹配技术证据的完整候选清单")
            for decision in decisions:
                item = _find_item_dir(batch, decision["video_id"])
                current = workflow._review_media(batch, item, "视频.mp4")
                artifacts = decision.get("artifacts")
                evidence = artifacts.get("视频.mp4") if isinstance(artifacts, dict) else None
                snapshot = (state.human_gate or {}).get("candidates", {}).get(decision["video_id"])
                technical = json.loads((item / "_工作文件/验收记录/视频技术检查.json").read_text(encoding="utf-8"))
                raw_source = evidence.get("source_path") if isinstance(evidence, dict) else None
                source = (item / raw_source).resolve() if isinstance(raw_source, str) and raw_source else None
                allowed_paths = {(item / current["source_path"]).resolve(), Path(technical["candidate"]).resolve()}
                if (not isinstance(evidence, dict) or evidence.get("sha256") != current["sha256"]
                        or source not in allowed_paths
                        or evidence.get("version", current["version"]) != current["version"]
                        or (snapshot and (evidence.get("version") != snapshot["version"] or current["sha256"] != snapshot["sha256"] or current["version"] != snapshot["version"]))):
                    raise ValueError("最终验收通过或不通过都必须绑定本次报告候选的路径、哈希和版本")
            workflow.record_review(batch, args.result, args.knowledge_dir)
            try:
                _promote_passed_review_outputs(batch, args.result.resolve(), workflow)
            except ValueError as exc:
                reason = str(exc)
                state.pending_action = {"kind": "BLOCKED", "reason": reason}
                transition(state, "BLOCKED", reason=reason)
                result = {"kind": "BLOCKED", "reason": reason}
            else:
                audit = workflow.audit_batch_outputs(batch, video_ids=sorted(expected_ids))
                failures = _failed_review_items(args.result.resolve())
                try:
                    failures.update(_failed_audit_items(batch, audit, sorted(expected_ids)))
                except ValueError as exc:
                    reason = str(exc)
                    state.pending_action = {"kind": "BLOCKED", "reason": reason}
                    transition(state, "BLOCKED", reason=reason)
                    result = {"kind": "BLOCKED", "reason": reason}
                else:
                    if failures:
                        result = _route_video_failures(batch, state, failures)
                    else:
                        state.human_gate = None
                        for item in _video_items(batch):
                            if item.name.split("_", 1)[0] not in expected_ids:
                                continue
                            info = _task_info(item)
                            info.update({"status": "COMPLETED", "completed_at": _now()})
                            _write_task_info(item, info)
                        if all(_task_info(item).get("status") == "COMPLETED" for item in _video_items(batch)):
                            result = _finalize_outputs(batch, state)
                        else:
                            transition(state, "RUNNING_AUTOMATICALLY", reason="已验收项目完成，其余项目保留原版本继续")
                            result = next_action(batch, state, policy)
            save_state(batch, state)
        else:
            raise ValueError(f"未知命令：{args.command}")
        _print_compact(result)
        return 0
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        InvalidOperation,
        json.JSONDecodeError,
    ) as exc:
        if "state" in locals() and not (args.command == "run-local" and args.dry_run):
            state.history.append({"at": _now(), "command": args.command, "error": str(exc)})
            save_state(batch, state)
        _print_compact({"kind": "COMMAND_REJECTED", "reason": str(exc), "status": state.status if "state" in locals() else "INVALID_STATE"})
        return 2


def _archive_v01_for_rerun(item: Path) -> None:
    archive = item / "_工作文件/历史版本/视频版本/V01_初次生成"
    archive.mkdir(parents=True, exist_ok=True)
    for category, filename in (("生成过程", "视频候选.mp4"), ("生成过程", "视频提交提示词.txt"), ("任务状态", "提交请求.json"), ("验收记录", "视频技术检查.json"), ("验收记录", "自动验收报告.md"), ("任务状态", "AutoDL提交结果.json"), ("任务状态", "提交预览.json"), ("任务状态", "查询结果.json")):
        source = item / "_工作文件" / category / filename
        if source.is_file():
            target = archive / filename
            if target.exists() and _sha256(target) != _sha256(source):
                raise ValueError(f"V01 历史证据已存在且不同：{filename}")
            if not target.exists():
                shutil.copy2(source, target)
            source.unlink()


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with exclusive_lock(args.batch.resolve() / ".pipeline.lock"):
            return _main_locked(args)
    except (OSError, RuntimeError, ValueError) as exc:
        _print_compact({"kind": "COMMAND_BUSY", "reason": str(exc)})
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
