#!/usr/bin/env python3

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
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
    blocked_reason: str = ""
    history: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def new(cls, digest: str) -> "RunnerState":
        return cls(1, digest, "WAITING_START_APPROVAL")


def save_state(batch_dir: Path, state: RunnerState) -> Path:
    batch_dir.mkdir(parents=True, exist_ok=True)
    path = _state_path(batch_dir)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(asdict(state), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def load_or_create_state(batch_dir: Path, policy: dict[str, object]) -> RunnerState:
    path = _state_path(batch_dir)
    digest = _load_policy_module().policy_digest(policy)
    if not path.exists():
        state = RunnerState.new(digest)
        save_state(batch_dir, state)
        return state
    state = RunnerState(**json.loads(path.read_text(encoding="utf-8")))
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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)
    return path


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
    if state.status != "BLOCKED" or state.blocked_reason != blocked_reason:
        transition(state, "BLOCKED", reason=blocked_reason)
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
    )


def _poll_item(task_id: str, api_key: Optional[str]) -> dict[str, object]:
    autodl = _load_autodl()
    response = autodl.poll_task(task_id, api_key=api_key)
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
    return {
        "ok": True,
        "duration": duration,
        "width": width,
        "height": height,
        "has_audio": True,
        "sha256": _sha256(path),
    }


def run_autodl_item(
    batch_dir: Path,
    item_dir: Path,
    state: RunnerState,
    *,
    api_key: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, object]:
    video_id = item_dir.name.split("_", 1)[0]
    info = _task_info(item_dir)
    task_id = str(info.get("task_id") or "")
    submitted: dict[str, object] = {}
    if info.get("submission_pending") or (info.get("request_hash") and not task_id):
        return _reconciliation_required(
            state,
            item_dir,
            info,
            str(info.get("reconciliation_reason") or "存在未核对的提交请求身份"),
        )
    if not task_id:
        preview = _submit_item(item_dir, api_key, dry_run=True)
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "request_hash": preview["request_hash"],
            }
        assert_paid_submit_allowed(state, info, video_id)
        request_hash = str(preview.get("request_hash") or "")
        if not request_hash:
            raise ValueError("AutoDL 提交预览缺少 request_hash")
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
            workflow = _load_workflow_cli()
            workflow.record_task(
                batch_dir,
                video_id,
                task_id,
                request_id=submitted.get("request_id"),
                request_hash=request_hash,
            )
        except Exception as exc:
            if task_id:
                info["task_id"] = task_id
            return _reconciliation_required(state, item_dir, info, str(exc))
    polled = _poll_item(task_id, api_key)
    resumed_task_id = task_id if not submitted else ""
    if polled["status"] not in {"success", "succeeded", "completed"}:
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
    return {
        "ok": bool(technical["ok"]),
        "task_id": task_id,
        "resumed_task_id": resumed_task_id,
        "candidate": str(candidate.resolve()),
        "technical": technical,
    }


def normalize_web_image(
    source: Path, output: Path, *, width: int = 2160, height: int = 3840
) -> dict[str, object]:
    source = Path(source).resolve()
    output = Path(output).resolve()
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError("GPT 网页图片不存在或为空")
    if width <= 0 or height <= 0:
        raise ValueError("图片目标尺寸必须为正数")
    try:
        with Image.open(source) as image:
            image.load()
            source_size = image.size
            if image.width * 16 != image.height * 9:
                raise ValueError("GPT 网页图片必须为 9:16，禁止自动裁切或拉伸")
            normalized = image.convert("RGB").resize(
                (width, height), Image.Resampling.LANCZOS
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(output.suffix + ".tmp")
            normalized.save(temporary, format="PNG")
            temporary.replace(output)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("GPT 网页图片无法在本地解码") from exc
    return {
        "source_size": list(source_size),
        "target_size": [width, height],
        "sha256": _sha256(output),
    }


def accept_web_image(item_dir: Path, artifact_name: str, source: Path) -> dict[str, object]:
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
    technical = normalize_web_image(source, candidate)
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
        "GPT 网页结果按图片免审规则完成本地技术检查并自动晋升",
    )
    promoted = workflow.promote_approved_artifact(item_dir, event)
    return {
        "ok": True,
        "provider": "gpt_web",
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
    state: RunnerState, *, video_id: str, artifact: str, reason: str
) -> dict[str, object]:
    key = f"{video_id}:{artifact}"
    failures = state.image_failures.get(key, 0) + 1
    state.image_failures[key] = failures
    if failures == 1:
        return {
            "kind": "RETRY_GPT_WEB_IMAGE",
            "video_id": video_id,
            "artifact": artifact,
            "attempt": 2,
            "reason": reason,
        }
    transition(state, "BLOCKED", reason=f"{key} 两次技术失败：{reason}")
    return {"kind": "BLOCKED", "reason": state.blocked_reason}


def _video_items(batch_dir: Path) -> list[Path]:
    return sorted(
        path for path in batch_dir.iterdir() if path.is_dir() and path.name.startswith("V")
    )


def accept_batch_content(
    batch_dir: Path, content_dir: Path, profile_path: Path
) -> dict[str, object]:
    workflow = _load_workflow_cli()
    accepted: list[str] = []
    for item in _video_items(batch_dir):
        video_id = item.name.split("_", 1)[0]
        content_path = content_dir / f"{video_id}.json"
        if not content_path.is_file():
            raise ValueError(f"缺少结构化内容：{content_path}")
        workflow.save_content_package(item, content_path, profile_path)
        accepted.append(video_id)
    return {"ok": True, "accepted": accepted}


def next_action(
    batch_dir: Path, state: RunnerState, policy: dict[str, object]
) -> dict[str, object]:
    if state.status == "WAITING_START_APPROVAL":
        return {"kind": "USER_START_APPROVAL_REQUIRED"}
    if state.status == "BLOCKED":
        return {"kind": "BLOCKED", "reason": state.blocked_reason}
    if state.status == "WAITING_RERUN_APPROVAL":
        return state.pending_action or {"kind": "USER_RERUN_APPROVAL_REQUIRED"}
    if state.status == "WAITING_FINAL_REVIEW":
        return {"kind": "USER_FINAL_REVIEW_REQUIRED"}
    if state.status == "COMPLETED":
        return {"kind": "DONE"}
    for item in _video_items(batch_dir):
        video_id = item.name.split("_", 1)[0]
        process = item / "_工作文件" / "生成过程"
        for artifact, prompt_name, raw_name in (
            ("分镜图.png", "分镜提示词.txt", "GPT网页原始分镜.png"),
            ("尾帧图.png", "合理尾帧提示词.txt", "GPT网页原始尾帧.png"),
            ("封面图.png", "封面提示词.txt", "GPT网页原始封面.png"),
        ):
            if not (item / artifact).exists() and (process / prompt_name).exists():
                return {
                    "kind": "GPT_WEB_IMAGE_REQUIRED",
                    "video_id": video_id,
                    "artifact": artifact,
                    "prompt_path": str((process / prompt_name).resolve()),
                    "output_path": str((process / raw_name).resolve()),
                }
    return {
        "kind": "BATCH_CONTENT_REQUIRED",
        "output_dir": str((batch_dir / "_批次内容").resolve()),
    }


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
        state.pending_action = action
        transition(
            state,
            "WAITING_RERUN_APPROVAL",
            reason=f"V01 失败，等待 V02 授权：{','.join(rerunnable)}",
        )
        save_state(batch_dir, state)
        return action

    reason = f"V02 已失败且禁止再次重跑：{','.join(terminal)}"
    state.pending_action = {
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


def _failed_audit_items(
    batch_dir: Path, audit: dict[str, object]
) -> dict[str, str]:
    failures: dict[str, str] = {}
    if audit.get("errors"):
        raise ValueError("最终七项产出审计失败且无法定位视频项目：批次级错误")
    items = audit.get("items", [])
    if not isinstance(items, list):
        raise ValueError("最终七项产出审计结果无效：items 必须为列表")
    expected = {
        item.name.split("_", 1)[0]: item.resolve() for item in _video_items(batch_dir)
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
    if state.status not in {"RUNNING_AUTOMATICALLY", "GENERATING"}:
        return next_action(batch_dir, state, policy)
    items = _video_items(batch_dir)
    if not items:
        return next_action(batch_dir, state, policy)
    workflow = _load_workflow_cli()
    failures: dict[str, str] = {}
    polling: list[str] = []
    for item in items:
        video_id = item.name.split("_", 1)[0]
        if "video" in state.completed_nodes.get(video_id, []):
            continue
        required = ("分镜图.png", "尾帧图.png", "封面图.png")
        if not all(
            workflow.validated_promoted_artifact_path(item, artifact) is not None
            for artifact in required
        ):
            return next_action(batch_dir, state, policy)
        result = run_autodl_item(batch_dir, item, state, dry_run=dry_run)
        if not result.get("ok"):
            if (
                state.status == "BLOCKED"
                or result.get("status") == "RECONCILIATION_REQUIRED"
            ):
                reason = state.blocked_reason or str(
                    result.get("reason", "付费提交状态需要人工核对")
                )
                if state.status != "BLOCKED":
                    transition(state, "BLOCKED", reason=reason)
                save_state(batch_dir, state)
                return {"kind": "BLOCKED", "reason": state.blocked_reason}
            if result.get("status") == "poll_timeout" and result.get("task_id"):
                polling.append(video_id)
                continue
            reason = state.blocked_reason or str(result.get("status", "视频执行失败"))
            failures[video_id] = str(result.get("reason") or reason)
            continue
        completed = state.completed_nodes.setdefault(video_id, [])
        if "video" not in completed:
            completed.append("video")
    if failures:
        return _route_video_failures(batch_dir, state, failures)
    if polling:
        action = {"kind": "VIDEO_POLL_PENDING", "video_ids": polling}
        state.pending_action = action
        transition(state, "GENERATING", reason=f"继续轮询：{','.join(polling)}")
        save_state(batch_dir, state)
        return action
    state.pending_action = None
    transition(state, "WAITING_FINAL_REVIEW", reason="全部视频候选准备完成")
    save_state(batch_dir, state)
    return {"kind": "USER_FINAL_REVIEW_REQUIRED"}


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
    content = sub.add_parser("accept-content")
    content.add_argument("--batch", type=Path, required=True)
    content.add_argument("--content-dir", type=Path, required=True)
    content.add_argument("--profile", type=Path, required=True)
    image = sub.add_parser("accept-image")
    image.add_argument("--batch", type=Path, required=True)
    image.add_argument("--video-id", required=True)
    image.add_argument(
        "--artifact",
        choices=("分镜图.png", "尾帧图.png", "封面图.png"),
        required=True,
    )
    image.add_argument("--source", type=Path, required=True)
    image_failed = sub.add_parser("image-failed")
    image_failed.add_argument("--batch", type=Path, required=True)
    image_failed.add_argument("--video-id", required=True)
    image_failed.add_argument(
        "--artifact",
        choices=("分镜图.png", "尾帧图.png", "封面图.png"),
        required=True,
    )
    image_failed.add_argument("--reason", required=True)
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
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        skill_root = Path(__file__).resolve().parents[1]
        policy = _load_policy_module().load_policy(skill_root)
        batch = args.batch.resolve()
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
            state.approved_budget = str(approved)
            state.estimated_v01_total = str(estimated)
            transition(state, "RUNNING_AUTOMATICALLY", reason="V01 总预算已确认")
            save_state(batch, state)
            result = next_action(batch, state, policy)
        elif args.command == "accept-content":
            consume_model_call(state, policy, video_id=None)
            save_state(batch, state)
            result = accept_batch_content(
                batch, args.content_dir.resolve(), args.profile.resolve()
            )
            save_state(batch, state)
        elif args.command == "accept-image":
            item = _find_item_dir(batch, args.video_id)
            consume_model_call(state, policy, video_id=args.video_id)
            save_state(batch, state)
            result = accept_web_image(item, args.artifact, args.source)
            save_state(batch, state)
        elif args.command == "image-failed":
            _find_item_dir(batch, args.video_id)
            consume_model_call(state, policy, video_id=args.video_id)
            save_state(batch, state)
            result = record_image_failure(
                state,
                video_id=args.video_id,
                artifact=args.artifact,
                reason=args.reason,
            )
            save_state(batch, state)
        elif args.command == "run-local":
            result = run_local_until_gate(batch, state, policy, dry_run=args.dry_run)
        elif args.command == "approve-rerun":
            if state.status != "WAITING_RERUN_APPROVAL":
                raise ValueError("当前状态不允许批准 V02 重跑")
            pending_ids = (
                state.pending_action.get("video_ids", [])
                if isinstance(state.pending_action, dict)
                else []
            )
            if args.video_id not in pending_ids:
                raise ValueError(f"{args.video_id} 不在待批准 V02 的失败项目中")
            rerun_cost = _positive_authorization_amount(
                args.approved_cost, "V02 批准费用"
            )
            workflow = _load_workflow_cli()
            workflow.start_rerun(batch, args.video_id)
            state.rerun_budget_by_video[args.video_id] = str(rerun_cost)
            state.pending_action = None
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
            workflow.record_review(batch, args.result, args.knowledge_dir)
            try:
                _promote_passed_review_outputs(batch, args.result.resolve(), workflow)
            except ValueError as exc:
                reason = str(exc)
                state.pending_action = {"kind": "BLOCKED", "reason": reason}
                transition(state, "BLOCKED", reason=reason)
                result = {"kind": "BLOCKED", "reason": reason}
            else:
                audit = workflow.audit_batch_outputs(batch)
                failures = _failed_review_items(args.result.resolve())
                try:
                    failures.update(_failed_audit_items(batch, audit))
                except ValueError as exc:
                    reason = str(exc)
                    state.pending_action = {"kind": "BLOCKED", "reason": reason}
                    transition(state, "BLOCKED", reason=reason)
                    result = {"kind": "BLOCKED", "reason": reason}
                else:
                    if failures:
                        result = _route_video_failures(batch, state, failures)
                    else:
                        state.pending_action = None
                        transition(
                            state,
                            "COMPLETED",
                            reason="最终视频验收及七项产出审计通过",
                        )
                        result = {"kind": "DONE"}
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
        _print_compact({"kind": "BLOCKED", "reason": str(exc)})
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
