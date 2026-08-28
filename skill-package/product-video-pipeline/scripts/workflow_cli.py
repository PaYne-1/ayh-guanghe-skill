#!/usr/bin/env python3
"""Portable deterministic helpers for the product-video-pipeline skill.

This script never calls a paid model. It prepares batches, validates agent-created
content, records task IDs, and builds an offline human-review report.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import html
import json
import os
import re
import shutil
import sys
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
FIXED_SEGMENTS = [(0, 4), (4, 11), (11, 15)]
WINDOWS_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
TURNING_TERMS = (
    "转弯",
    "拐弯",
    "掉头",
    "原地转圈",
    "S形",
    "弧线",
    "绕行",
    "侧向移动",
    "倒车转向",
    "环绕",
)
FOLDING_PROCESS_TERMS = (
    "正在折叠",
    "正在展开",
    "折叠过程",
    "展开过程",
    "从展开到折叠",
    "从折叠到展开",
    "结构变化",
)
CTA_TERMS = ("可以看看", "可以了解", "可以考虑", "可以留意", "可以选择")
IMPROVEMENT_TERMS = (
    "方便",
    "轻松",
    "省心",
    "省力",
    "顺手",
    "愿意下楼",
    "不用总麻烦",
)
DELIVERABLE_NAMES = {"视频.mp4", "封面图.png", "发布正文.md", "标题.txt", "分镜图.png"}
WORK_DIR_NAME = "_工作文件"
WORK_CATEGORIES = ("任务状态", "生成过程", "验收记录", "历史版本")
TASK_STATE_PREFIXES = (
    "任务信息",
    "查询结果",
    "查询日志",
    "提交请求",
    "提交预览",
    "正式提交日志",
    "AutoDL",
    "dry-run日志",
)
REVIEW_PREFIXES = (
    "自动验收报告",
    "口播音轨验收",
    "人工验收",
    "人工处理说明",
    "候选经验",
    "验收对比",
    "验收预览图",
)
HISTORY_DIR_NAMES = {"失败版本", "视频版本"}
ITEM_DIR_PATTERN = re.compile(r"^V\d{3}_")
APPROVAL_LOG_NAME = "产出验收记录.json"
APPROVAL_DECISIONS = {"passed", "failed", "revoked"}
_APPROVAL_THREAD_LOCKS: Dict[str, threading.Lock] = {}
_APPROVAL_THREAD_LOCKS_GUARD = threading.Lock()


class BatchItem:
    def __init__(self, video_id: str, selling_point: str, project_dir: Path):
        self.video_id = video_id
        self.selling_point = selling_point
        self.project_dir = project_dir


class BatchContext:
    def __init__(self, batch_dir: Path, product_images: Sequence[Path], items: Sequence[BatchItem]):
        self.batch_dir = batch_dir
        self.product_images = tuple(product_images)
        self.items = tuple(items)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def atomic_write_json(path: Path, value: object) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2))


@contextlib.contextmanager
def _approval_log_lock(item_dir: Path):
    lock_path = approval_log_path(item_dir).with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    key = str(lock_path.resolve()).casefold()
    with _APPROVAL_THREAD_LOCKS_GUARD:
        thread_lock = _APPROVAL_THREAD_LOCKS.setdefault(key, threading.Lock())
    with thread_lock:
        with lock_path.open("a+b") as stream:
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def read_json(path: Path, default: Optional[object] = None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_work_dirs(item_dir: Path) -> Dict[str, Path]:
    work_root = item_dir / WORK_DIR_NAME
    paths = {category: work_root / category for category in WORK_CATEGORIES}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def work_path(item_dir: Path, category: str, filename: str) -> Path:
    if category not in WORK_CATEGORIES:
        raise ValueError(f"未知工作文件分类：{category}")
    return item_dir / WORK_DIR_NAME / category / filename


def read_compatible_path(item_dir: Path, category: str, filename: str) -> Path:
    preferred = work_path(item_dir, category, filename)
    return preferred if preferred.exists() else item_dir / filename


def approval_log_path(item_dir: Path) -> Path:
    return work_path(item_dir, "验收记录", APPROVAL_LOG_NAME)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_approval_events(item_dir: Path) -> List[Dict[str, object]]:
    payload = read_json(approval_log_path(item_dir), {"events": []})
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("产出验收记录格式错误：必须包含 events 数组")
    if any(not isinstance(event, dict) for event in payload["events"]):
        raise ValueError("产出验收记录格式错误：events 只能包含对象")
    return list(payload["events"])


def latest_artifact_decision(
    events: Sequence[Dict[str, object]],
    artifact_name: str,
    sha256: str,
) -> Optional[Dict[str, object]]:
    return next(
        (
            event
            for event in reversed(events)
            if event.get("artifact_name") == artifact_name and event.get("sha256") == sha256
        ),
        None,
    )


def _snapshot_review_candidate(
    item_dir: Path,
    artifact_name: str,
    source_path: Path,
    digest: str,
    confirmed_at: datetime,
) -> Path:
    artifact = Path(artifact_name)
    snapshot_dir = work_path(item_dir, "历史版本", "验收候选") / artifact.stem
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    timestamp = confirmed_at.strftime("%Y%m%dT%H%M%S%f%z")
    snapshot = snapshot_dir / f"{timestamp}_{digest[:12]}{artifact.suffix}"
    counter = 2
    while snapshot.exists():
        if snapshot.is_file() and _sha256_file(snapshot) == digest:
            return snapshot
        snapshot = snapshot_dir / f"{timestamp}_{digest[:12]}_{counter}{artifact.suffix}"
        counter += 1
    temporary = snapshot.with_suffix(snapshot.suffix + f".tmp.{uuid.uuid4().hex}")
    try:
        shutil.copyfile(source_path, temporary)
        if _sha256_file(temporary) != digest:
            raise OSError(f"验收候选快照哈希校验失败：{source_path}")
        temporary.replace(snapshot)
    finally:
        if temporary.exists():
            temporary.unlink()
    return snapshot


def record_artifact_decision(
    item_dir: Path,
    artifact_name: str,
    source_path: Path,
    decision: str,
    confirmed_by: str,
    feedback: str,
    now: Optional[datetime] = None,
) -> Dict[str, object]:
    item_dir = item_dir.resolve()
    if not item_dir.is_dir() or not ITEM_DIR_PATTERN.match(item_dir.name):
        raise ValueError(f"不是有效的单条任务目录：{item_dir}")
    if artifact_name not in DELIVERABLE_NAMES:
        raise ValueError(f"未知产出名称：{artifact_name}")
    if decision not in APPROVAL_DECISIONS:
        raise ValueError(f"验收决定只能是 passed、failed 或 revoked：{decision}")
    if not confirmed_by.strip():
        raise ValueError("确认人不能为空")
    if not feedback.strip():
        raise ValueError("验收反馈不能为空")

    source_path = source_path if source_path.is_absolute() else item_dir / source_path
    source_path = source_path.resolve()
    try:
        relative_source = source_path.relative_to(item_dir)
    except ValueError as exc:
        raise ValueError("候选文件必须位于单条任务目录内") from exc
    if not source_path.is_file():
        raise ValueError(f"候选文件不存在或不是普通文件：{source_path}")
    if source_path.parent == item_dir and source_path.name in DELIVERABLE_NAMES:
        raise ValueError("候选文件不能是一级固定产出，必须来自 _工作文件")

    confirmed_at = now or datetime.now().astimezone()
    if confirmed_at.utcoffset() is None:
        raise ValueError("确认时间必须包含时区")
    digest = _sha256_file(source_path)
    snapshot = _snapshot_review_candidate(item_dir, artifact_name, source_path, digest, confirmed_at)
    event: Dict[str, object] = {
        "event_id": str(uuid.uuid4()),
        "artifact_name": artifact_name,
        "source_path": snapshot.relative_to(item_dir).as_posix(),
        "submitted_source_path": relative_source.as_posix(),
        "sha256": digest,
        "decision": decision,
        "confirmed_by": confirmed_by.strip(),
        "confirmed_at": confirmed_at.isoformat(),
        "feedback": feedback.strip(),
    }
    with _approval_log_lock(item_dir):
        events = load_approval_events(item_dir)
        events.append(event)
        atomic_write_json(approval_log_path(item_dir), {"events": events})
    return event


def _unique_artifact_archive_path(
    item_dir: Path,
    subdirectory: str,
    artifact_name: str,
    sha256: str,
    now: datetime,
) -> Path:
    archive_dir = work_path(item_dir, "历史版本", subdirectory)
    artifact = Path(artifact_name)
    timestamp = now.strftime("%Y%m%dT%H%M%S%z")
    base_name = f"{artifact.stem}_{timestamp}_{sha256[:8]}"
    candidate = archive_dir / f"{base_name}{artifact.suffix}"
    counter = 2
    while candidate.exists():
        candidate = archive_dir / f"{base_name}_{counter}{artifact.suffix}"
        counter += 1
    return candidate


def _archive_root_artifact(
    item_dir: Path,
    root_artifact: Path,
    subdirectory: str,
    now: datetime,
    *,
    dry_run: bool = False,
) -> Path:
    digest = _sha256_file(root_artifact)
    target = _unique_artifact_archive_path(item_dir, subdirectory, root_artifact.name, digest, now)
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(root_artifact), str(target))
    return target


def promote_approved_artifact(item_dir: Path, event: Dict[str, object]) -> Path:
    item_dir = item_dir.resolve()
    artifact_name = str(event.get("artifact_name", ""))
    if artifact_name not in DELIVERABLE_NAMES or event.get("decision") != "passed":
        raise ValueError("只有五项固定产出的 passed 事件可以晋升")
    events = load_approval_events(item_dir)
    recorded = next((value for value in events if value.get("event_id") == event.get("event_id")), None)
    if recorded is None:
        raise ValueError("passed 事件尚未写入产出验收记录")
    digest = str(recorded.get("sha256", ""))
    latest = latest_artifact_decision(events, artifact_name, digest)
    if latest is None or latest.get("event_id") != recorded.get("event_id") or latest.get("decision") != "passed":
        raise ValueError("该候选的最新验收决定不是 passed")

    source = (item_dir / str(recorded["source_path"])).resolve()
    try:
        source.relative_to(item_dir)
    except ValueError as exc:
        raise ValueError("验收事件的候选路径已越出任务目录") from exc
    if not source.is_file() or _sha256_file(source) != digest:
        raise ValueError("候选文件缺失或哈希已变化，不能晋升")

    root_artifact = item_dir / artifact_name
    if root_artifact.exists():
        if not root_artifact.is_file():
            raise ValueError(f"一级固定产出路径不是文件：{root_artifact}")
        if _sha256_file(root_artifact) == digest:
            return root_artifact
    confirmed_at = datetime.fromisoformat(str(recorded["confirmed_at"]))
    temporary = root_artifact.with_name(root_artifact.name + f".tmp.{uuid.uuid4().hex}")
    archived_previous: Optional[Path] = None
    try:
        shutil.copyfile(source, temporary)
        if _sha256_file(temporary) != digest:
            raise OSError(f"晋升临时文件哈希校验失败：{source}")
        if root_artifact.exists():
            old_digest = _sha256_file(root_artifact)
            archived_previous = _unique_artifact_archive_path(
                item_dir, "已撤换产出", artifact_name, old_digest, confirmed_at
            )
            archived_previous.parent.mkdir(parents=True, exist_ok=True)
            root_artifact.replace(archived_previous)
        try:
            temporary.replace(root_artifact)
            if _sha256_file(root_artifact) != digest:
                raise OSError(f"晋升后哈希校验失败：{root_artifact}")
        except Exception as promote_error:
            rollback_error = None
            try:
                if root_artifact.exists() and root_artifact.is_file():
                    failed_digest = _sha256_file(root_artifact)
                    failed_target = _unique_artifact_archive_path(
                        item_dir, "晋升失败", artifact_name, failed_digest, confirmed_at
                    )
                    failed_target.parent.mkdir(parents=True, exist_ok=True)
                    root_artifact.replace(failed_target)
                if archived_previous is not None and archived_previous.exists():
                    archived_previous.replace(root_artifact)
            except Exception as exc:
                rollback_error = exc
            if rollback_error is not None:
                raise OSError(f"晋升失败且旧产出回滚失败：{rollback_error}") from promote_error
            raise
    finally:
        if temporary.exists():
            temporary.unlink()
    return root_artifact


def audit_promoted_outputs(
    item_dir: Path,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, object]:
    item_dir = item_dir.resolve()
    if not item_dir.is_dir() or not ITEM_DIR_PATTERN.match(item_dir.name):
        raise ValueError(f"不是有效的单条任务目录：{item_dir}")
    audit_time = now or datetime.now().astimezone()
    if audit_time.utcoffset() is None:
        raise ValueError("审计时间必须包含时区")

    errors: List[Dict[str, object]] = []
    try:
        events = load_approval_events(item_dir)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        events = []
        errors.append({"artifact_name": None, "error": str(exc)})

    valid = []
    demoted = []
    missing = []
    for artifact_name in sorted(DELIVERABLE_NAMES):
        root_artifact = item_dir / artifact_name
        if not root_artifact.exists():
            missing.append(artifact_name)
            continue
        if not root_artifact.is_file():
            errors.append({"artifact_name": artifact_name, "error": "一级固定产出路径不是文件"})
            continue
        digest = _sha256_file(root_artifact)
        try:
            latest = latest_artifact_decision(events, artifact_name, digest)
        except (ValueError, KeyError) as exc:
            latest = None
            errors.append({"artifact_name": artifact_name, "error": str(exc)})
        if latest is not None and latest.get("decision") == "passed":
            valid.append({"artifact_name": artifact_name, "sha256": digest, "event": latest})
            continue
        target = _archive_root_artifact(
            item_dir,
            root_artifact,
            "未通过或待验收",
            audit_time,
            dry_run=dry_run,
        )
        demoted.append(
            {
                "artifact_name": artifact_name,
                "sha256": digest,
                "target": str(target),
                "latest_event": latest,
            }
        )

    return {
        "item_dir": str(item_dir),
        "dry_run": dry_run,
        "promoted": [],
        "valid": valid,
        "demoted": demoted,
        "missing": missing,
        "errors": errors,
    }


def audit_batch_outputs(batch_dir: Path, dry_run: bool = False) -> Dict[str, object]:
    batch_dir = batch_dir.resolve()
    if not batch_dir.is_dir():
        raise ValueError(f"批次目录不存在：{batch_dir}")
    item_dirs = sorted(
        (path for path in batch_dir.iterdir() if path.is_dir() and ITEM_DIR_PATTERN.match(path.name)),
        key=lambda path: path.name.casefold(),
    )
    if not item_dirs:
        raise ValueError(f"批次目录第一层没有 VNNN_ 单条任务目录：{batch_dir}")
    return {
        "batch_dir": str(batch_dir),
        "dry_run": dry_run,
        "items": [audit_promoted_outputs(item_dir, dry_run=dry_run) for item_dir in item_dirs],
    }


def _audit_result_has_errors(result: Dict[str, object]) -> bool:
    if result.get("errors"):
        return True
    items = result.get("items", [])
    return isinstance(items, list) and any(
        isinstance(item, dict) and _audit_result_has_errors(item) for item in items
    )


def validated_promoted_artifact_path(item_dir: Path, artifact_name: str) -> Optional[Path]:
    if artifact_name not in DELIVERABLE_NAMES:
        raise ValueError(f"未知产出名称：{artifact_name}")
    root_artifact = item_dir / artifact_name
    if not root_artifact.is_file():
        return None
    try:
        digest = _sha256_file(root_artifact)
        latest = latest_artifact_decision(load_approval_events(item_dir), artifact_name, digest)
    except (ValueError, KeyError, json.JSONDecodeError):
        return None
    return root_artifact if latest is not None and latest.get("decision") == "passed" else None


def classify_legacy_entry(path: Path) -> Optional[Tuple[str, Path]]:
    if path.name in DELIVERABLE_NAMES or path.name == WORK_DIR_NAME:
        return None
    if path.name in HISTORY_DIR_NAMES:
        return "历史版本", Path(path.name)
    if path.name.startswith(TASK_STATE_PREFIXES):
        return "任务状态", Path(path.name)
    if path.name.startswith(REVIEW_PREFIXES):
        return "验收记录", Path(path.name)
    if path.is_file() and (
        (path.suffix.casefold() == ".mp4" and path.name != "视频.mp4")
        or path.name.startswith("封面图_")
    ):
        return "历史版本", Path(path.name)
    return "生成过程", Path(path.name)


def _entry_manifest(path: Path) -> Tuple[Tuple[str, str, str], ...]:
    if path.is_file():
        return ((path.name, "file", hashlib.sha256(path.read_bytes()).hexdigest()),)
    if not path.is_dir():
        return ()
    manifest = []
    for child in sorted(path.rglob("*"), key=lambda value: value.relative_to(path).as_posix().casefold()):
        relative = child.relative_to(path).as_posix()
        if child.is_dir():
            manifest.append((relative, "dir", ""))
        elif child.is_file():
            manifest.append((relative, "file", hashlib.sha256(child.read_bytes()).hexdigest()))
        else:
            manifest.append((relative, "other", ""))
    return tuple(manifest)


def _same_entry(source: Path, target: Path) -> bool:
    return source.is_file() == target.is_file() and source.is_dir() == target.is_dir() and _entry_manifest(source) == _entry_manifest(target)


def _next_duplicate_target(item_dir: Path, source: Path, reserved: set) -> Path:
    duplicate_root = work_path(item_dir, "历史版本", "重复项")
    candidate = duplicate_root / source.name
    counter = 2
    while candidate.exists() or candidate in reserved:
        if source.is_file():
            candidate = duplicate_root / f"{source.stem}_重复{counter}{source.suffix}"
        else:
            candidate = duplicate_root / f"{source.name}_重复{counter}"
        counter += 1
    return candidate


def organize_item_dir(item_dir: Path, dry_run: bool = False) -> Dict[str, object]:
    item_dir = item_dir.resolve()
    if not item_dir.is_dir():
        raise ValueError(f"单条任务目录不存在：{item_dir}")
    if not ITEM_DIR_PATTERN.match(item_dir.name):
        raise ValueError(f"不是单条任务目录，名称必须以 VNNN_ 开头：{item_dir}")

    output_audit = audit_promoted_outputs(item_dir, dry_run=True)
    plan = []
    duplicates = []
    reserved_duplicate_targets = set()
    conflicts = []
    for source in sorted(item_dir.iterdir(), key=lambda path: path.name.casefold()):
        classification = classify_legacy_entry(source)
        if classification is None:
            continue
        category, relative_target = classification
        target = work_path(item_dir, category, str(relative_target))
        if target.exists():
            if _same_entry(source, target):
                duplicate_target = _next_duplicate_target(item_dir, source, reserved_duplicate_targets)
                reserved_duplicate_targets.add(duplicate_target)
                duplicates.append((source, target, duplicate_target))
                continue
            raise FileExistsError(f"目标已存在且内容不同，未移动任何文件：{source.name} -> {target}")
        plan.append((source, target))

    if not dry_run:
        output_audit = audit_promoted_outputs(item_dir)
        ensure_work_dirs(item_dir)
        for source, target in plan:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        for source, _existing, duplicate_target in duplicates:
            duplicate_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(duplicate_target))

    planned_sources = {source for source, _target in plan} | {source for source, _existing, _target in duplicates}
    if dry_run:
        remaining_forbidden = [
            path.name
            for path in item_dir.iterdir()
            if classify_legacy_entry(path) is not None and path not in planned_sources
        ]
    else:
        remaining_forbidden = [path.name for path in item_dir.iterdir() if classify_legacy_entry(path) is not None]

    return {
        "item_dir": str(item_dir),
        "dry_run": dry_run,
        "moved": [{"source": str(source), "target": str(target)} for source, target in plan],
        "duplicates": [
            {"source": str(source), "existing": str(existing), "archived": str(duplicate_target)}
            for source, existing, duplicate_target in duplicates
        ],
        "unchanged": sorted(name for name in DELIVERABLE_NAMES if (item_dir / name).exists()),
        "conflicts": conflicts,
        "root_clean": not remaining_forbidden,
        "remaining_forbidden": sorted(remaining_forbidden),
        "output_audit": output_audit,
    }


def organize_batch_dir(batch_dir: Path, dry_run: bool = False) -> Dict[str, object]:
    batch_dir = batch_dir.resolve()
    if not batch_dir.is_dir():
        raise ValueError(f"批次目录不存在：{batch_dir}")
    item_dirs = sorted(
        (path for path in batch_dir.iterdir() if path.is_dir() and ITEM_DIR_PATTERN.match(path.name)),
        key=lambda path: path.name.casefold(),
    )
    if not item_dirs:
        raise ValueError(f"批次目录第一层没有 VNNN_ 单条任务目录：{batch_dir}")
    return {
        "batch_dir": str(batch_dir),
        "dry_run": dry_run,
        "items": [organize_item_dir(item_dir, dry_run=dry_run) for item_dir in item_dirs],
    }


def sanitize_component(value: str, limit: int = 36) -> str:
    cleaned = WINDOWS_FORBIDDEN.sub("_", value).strip().rstrip(".")
    cleaned = re.sub(r"\s+", "_", cleaned)
    return (cleaned or "未命名")[:limit]


def scan_product_images(product_dir: Path) -> Tuple[Path, ...]:
    product_dir = product_dir.resolve()
    if not product_dir.is_dir():
        raise ValueError(f"产品文件夹不存在：{product_dir}")
    return tuple(
        sorted(
            (
                path.resolve()
                for path in product_dir.iterdir()
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
            ),
            key=lambda path: path.name.casefold(),
        )
    )


def scan_cover_references(reference_dir: Path) -> Tuple[Path, ...]:
    reference_dir = reference_dir.resolve()
    if not reference_dir.is_dir():
        raise ValueError(f"封面图参考文件夹不存在：{reference_dir}")
    return tuple(
        sorted(
            (
                path.resolve()
                for path in reference_dir.iterdir()
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
            ),
            key=lambda path: path.name.casefold(),
        )
    )


def allocate_video_points(selling_points: Sequence[str], total_videos: int) -> Tuple[str, ...]:
    points = tuple(point.strip() for point in selling_points if point.strip())
    if not points:
        raise ValueError("至少提供一个卖点")
    if total_videos <= 0:
        raise ValueError("视频总数必须大于 0")
    base, remainder = divmod(total_videos, len(points))
    allocation: List[str] = []
    for index, point in enumerate(points):
        allocation.extend([point] * (base + (1 if index < remainder else 0)))
    return tuple(allocation)


def _next_batch_dir(product_dir: Path, now: datetime) -> Path:
    output_root = product_dir / "生成视频"
    output_root.mkdir(parents=True, exist_ok=True)
    prefix = now.strftime("%Y%m%d")
    numbers = []
    for path in output_root.iterdir():
        match = re.fullmatch(rf"{prefix}_批次(\d{{3}})", path.name) if path.is_dir() else None
        if match:
            numbers.append(int(match.group(1)))
    return output_root / f"{prefix}_批次{(max(numbers, default=0) + 1):03d}"


def _product_id(product_name: str) -> str:
    digest = hashlib.sha256(product_name.strip().encode("utf-8")).hexdigest()[:10]
    return f"{sanitize_component(product_name, 24)}_{digest}"


def _record_selling_points(
    knowledge_dir: Path,
    product_name: str,
    product_dir: Path,
    selling_points: Sequence[str],
    now: datetime,
) -> Path:
    library_dir = knowledge_dir.resolve() / "产品卖点库"
    library_path = library_dir / f"{_product_id(product_name)}.json"
    value = read_json(
        library_path,
        {
            "product_name": product_name,
            "product_id": _product_id(product_name),
            "last_product_path": str(product_dir.resolve()),
            "selling_points": [],
        },
    )
    existing = {entry["content"]: entry for entry in value["selling_points"]}
    timestamp = now.astimezone(timezone.utc).isoformat()
    for point in dict.fromkeys(point.strip() for point in selling_points if point.strip()):
        if point in existing:
            existing[point]["last_used_at"] = timestamp
            existing[point]["use_count"] = int(existing[point].get("use_count", 0)) + 1
        else:
            entry = {
                "category": "待本次内容分析分类",
                "content": point,
                "first_used_at": timestamp,
                "last_used_at": timestamp,
                "use_count": 1,
            }
            value["selling_points"].append(entry)
            existing[point] = entry
    value["last_product_path"] = str(product_dir.resolve())
    value["updated_at"] = timestamp
    value["selling_points"].sort(key=lambda entry: entry["content"])
    atomic_write_json(library_path, value)
    return library_path


def initialize_batch(
    *,
    product_dir: Path,
    product_name: str,
    selling_points: Sequence[str],
    total_videos: int,
    run_mode: str,
    resolution: str,
    max_budget_yuan: str,
    cover_reference_dir: Path,
    knowledge_dir: Path,
    now: Optional[datetime] = None,
    text_provider: str = "任务开始前确认",
    image_provider: str = "原生生图优先；无原生能力时使用已确认 API",
) -> BatchContext:
    if run_mode not in {"learning", "auto"}:
        raise ValueError("运行模式只能是 learning 或 auto")
    if resolution not in {"768P", "2K"}:
        raise ValueError("分辨率只能是 768P 或 2K")
    try:
        if Decimal(max_budget_yuan) <= 0:
            raise ValueError("本批次最高预算必须大于 0")
    except InvalidOperation as exc:
        raise ValueError("预算必须是有效金额") from exc

    product_dir = product_dir.resolve()
    images = scan_product_images(product_dir)
    if not images:
        raise ValueError("产品文件夹第一层没有可用图片")
    cover_refs = scan_cover_references(cover_reference_dir)
    if not cover_refs:
        raise ValueError("封面图参考文件夹第一层没有可用图片")
    allocated = allocate_video_points(selling_points, total_videos)
    now = now or datetime.now().astimezone()
    batch_dir = _next_batch_dir(product_dir, now)
    batch_dir.mkdir(parents=True, exist_ok=False)

    items: List[BatchItem] = []
    task_rows = []
    for index, point in enumerate(allocated, start=1):
        video_id = f"V{index:03d}"
        project_dir = batch_dir / f"{video_id}_{sanitize_component(point, 20)}_待生成"
        ensure_work_dirs(project_dir)
        (work_path(project_dir, "历史版本", "视频版本") / "V01_初次生成").mkdir(parents=True)
        work_path(project_dir, "历史版本", "失败版本").mkdir(parents=True)
        task_info = {
            "video_id": video_id,
            "selling_point": point,
            "status": "CREATED",
            "task_id": None,
            "request_id": None,
            "request_hash": None,
            "retry_count": 0,
            "project_dir": str(project_dir.resolve()),
        }
        atomic_write_json(work_path(project_dir, "任务状态", "任务信息.json"), task_info)
        task_rows.append(task_info)
        items.append(BatchItem(video_id, point, project_dir))

    library_path = _record_selling_points(
        knowledge_dir=knowledge_dir,
        product_name=product_name,
        product_dir=product_dir,
        selling_points=selling_points,
        now=now,
    )
    confirmation = {
        "confirmed": False,
        "confirmation_scope": "任务开始前一次性确认；运行中不补问普通配置",
        "product_dir": str(product_dir),
        "product_name": product_name,
        "product_images": [str(path) for path in images],
        "selling_points": list(selling_points),
        "total_videos": total_videos,
        "allocation": {point: allocated.count(point) for point in dict.fromkeys(allocated)},
        "run_mode": run_mode,
        "text_provider": text_provider,
        "image_provider": image_provider,
        "cover_reference_dir": str(cover_reference_dir.resolve()),
        "video_provider": "AutoDL.Art MiniMax-H3",
        "duration_seconds": 15,
        "ratio": "9:16",
        "resolution": resolution,
        "aigc_watermark": False,
        "audio": "MiniMax-H3 原生对白；按人物清单匹配音色；轻微环境声；无 BGM",
        "image_max_attempts": 3,
        "video_max_reruns": 1,
        "concurrency": 3,
        "poll_interval_seconds": 20,
        "poll_timeout_seconds": 3600,
        "max_budget_yuan": str(Decimal(max_budget_yuan)),
        "live_price": "任务开始前查询并填写",
        "knowledge_library": str(library_path.resolve()),
        "created_at": now.isoformat(),
    }
    atomic_write_json(batch_dir / "启动确认单.json", confirmation)
    atomic_write_json(batch_dir / "批次任务表.json", {"items": task_rows})
    atomic_write_text(batch_dir / "批次汇总.md", "# 批次汇总\n\n状态：等待启动确认\n")
    return BatchContext(batch_dir, images, items)


def _han_count(value: str) -> int:
    return sum("\u4e00" <= char <= "\u9fff" for char in value)


def _closing_is_valid(dialogue: str, product_name: str) -> bool:
    used = any(term in dialogue for term in ("买了", "用了", "使用了", "换了"))
    has_product = product_name in dialogue
    after = "后" in dialogue
    benefit = any(term in dialogue for term in IMPROVEMENT_TERMS)
    cta = any(term in dialogue for term in CTA_TERMS)
    return used and has_product and after and benefit and cta


def validate_content_package(package: Dict[str, object], profile: Dict[str, object]) -> List[str]:
    issues: List[str] = []

    title = str(package.get("publish_title", ""))
    required_title_term = str(profile["required_title_term"])
    if required_title_term not in title:
        issues.append("title.required_term")
    title_chars = _han_count(title)
    if not 12 <= title_chars <= 28:
        issues.append("title.length")

    cover_title = str(package.get("cover_title", ""))
    if not int(profile["cover_title_min_chars"]) <= _han_count(cover_title) <= int(profile["cover_title_max_chars"]):
        issues.append("cover_title.length")

    people = package.get("people") if isinstance(package.get("people"), list) else []
    required_person_fields = {"id", "identity", "gender", "age_feel", "position", "action", "speaks"}
    if not people or any(not required_person_fields <= set(person) for person in people if isinstance(person, dict)):
        issues.append("people.fields_missing")
    people_ids = [str(person.get("id")) for person in people if isinstance(person, dict)]
    storyboard_people = [str(value) for value in package.get("storyboard_people", [])]
    if people_ids != storyboard_people:
        issues.append("people.mismatch")

    segments = package.get("script_segments") if isinstance(package.get("script_segments"), list) else []
    segment_ranges = [(segment.get("start"), segment.get("end")) for segment in segments if isinstance(segment, dict)]
    if segment_ranges != FIXED_SEGMENTS:
        issues.append("script.timeline")
    if any(str(segment.get("speaker_id")) not in people_ids for segment in segments if isinstance(segment, dict)):
        issues.append("people.offscreen_speaker")
    closing = str(segments[-1].get("dialogue", "")) if segments and isinstance(segments[-1], dict) else ""
    if not _closing_is_valid(closing, str(profile["closing_product_name"])):
        issues.append("closing.missing_improvement_and_cta")

    video_prompt = str(package.get("video_prompt", ""))
    if any(term.casefold() in video_prompt.casefold() for term in TURNING_TERMS):
        issues.append("motion.turning_forbidden")
    if any(term in video_prompt for term in FOLDING_PROCESS_TERMS):
        issues.append("folding.dynamic_process_forbidden")
    if not any(term in video_prompt for term in ("一镜到底", "固定镜头", "同一个镜头")):
        issues.append("shot.single_required")

    body = str(package.get("publish_body", ""))
    body_chars = _han_count(body)
    if not int(profile["body_min_chars"]) <= body_chars <= int(profile["body_max_chars"]):
        issues.append("body.length")
    if list(package.get("hashtags", [])) != list(profile["fixed_hashtags"]):
        issues.append("body.hashtags")

    return list(dict.fromkeys(issues))


def _write_candidate_preserving_previous(item_dir: Path, filename: str, text: str, now: datetime) -> None:
    target = work_path(item_dir, "生成过程", filename)
    encoded = text.encode("utf-8")
    new_digest = hashlib.sha256(encoded).hexdigest()
    if target.exists():
        if not target.is_file():
            raise ValueError(f"候选路径不是普通文件：{target}")
        old_digest = _sha256_file(target)
        if old_digest == new_digest:
            return
        archive = _unique_artifact_archive_path(item_dir, "候选版本", filename, old_digest, now)
        archive.parent.mkdir(parents=True, exist_ok=True)
        target.replace(archive)
    temporary = target.with_name(target.name + f".tmp.{uuid.uuid4().hex}")
    try:
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(encoded)
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    if _sha256_file(target) != new_digest:
        raise OSError(f"候选文件写入后哈希校验失败：{target}")


def save_content_package(item_dir: Path, package_path: Path, profile_path: Path) -> None:
    package = read_json(package_path)
    profile = read_json(profile_path)
    issues = validate_content_package(package, profile)
    if issues:
        raise ValueError("内容校验失败：" + ", ".join(issues))
    ensure_work_dirs(item_dir)
    now = datetime.now().astimezone()
    _write_candidate_preserving_previous(
        item_dir,
        "策划内容.json",
        json.dumps(package, ensure_ascii=False, indent=2),
        now,
    )
    _write_candidate_preserving_previous(
        item_dir,
        "标题.txt",
        f"发布标题：{package['publish_title']}\n封面标题：{package['cover_title']}\n",
        now,
    )
    _write_candidate_preserving_previous(item_dir, "分镜提示词.txt", str(package["storyboard_prompt"]), now)
    _write_candidate_preserving_previous(item_dir, "视频提示词.txt", str(package["video_prompt"]), now)
    tags = " ".join(package["hashtags"])
    _write_candidate_preserving_previous(item_dir, "发布正文.md", f"{package['publish_body']}\n\n{tags}\n", now)


def _find_item(batch_dir: Path, video_id: str) -> Path:
    matches = [path for path in batch_dir.iterdir() if path.is_dir() and path.name.startswith(video_id + "_")]
    if len(matches) != 1:
        raise ValueError(f"无法唯一定位视频项目：{video_id}")
    return matches[0]


def record_task(
    batch_dir: Path,
    video_id: str,
    task_id: str,
    *,
    request_id: Optional[str] = None,
    request_hash: Optional[str] = None,
    status: str = "SUBMITTED",
    estimated_cost_yuan: Optional[str] = None,
) -> None:
    item_dir = _find_item(batch_dir, video_id)
    task_path = work_path(item_dir, "任务状态", "任务信息.json")
    task = read_json(read_compatible_path(item_dir, "任务状态", "任务信息.json"), {})
    if task.get("task_id") and task["task_id"] != task_id:
        raise ValueError("该视频已记录其他 task_id，禁止覆盖")
    task.update(
        {
            "task_id": task_id,
            "request_id": request_id,
            "request_hash": request_hash,
            "status": status,
            "estimated_cost_yuan": estimated_cost_yuan,
            "updated_at": datetime.now().astimezone().isoformat(),
        }
    )
    atomic_write_json(task_path, task)
    table_path = batch_dir / "批次任务表.json"
    table = read_json(table_path, {"items": []})
    for row in table["items"]:
        if row["video_id"] == video_id:
            row.update(task)
            break
    atomic_write_json(table_path, table)


def _safe_file_url(item_dir: Path, filename: str) -> str:
    path = validated_promoted_artifact_path(item_dir, filename)
    return quote(f"{item_dir.name}/{filename}") if path is not None else ""


def _review_candidate_path(item_dir: Path, artifact_name: str) -> Optional[Path]:
    names = {
        "标题.txt": ("标题.txt",),
        "封面图.png": ("封面候选.png", "候选封面.png", "封面图.png"),
        "视频.mp4": ("视频候选.mp4", "候选视频.mp4"),
    }.get(artifact_name, ())
    process_dir = work_path(item_dir, "生成过程", "placeholder").parent
    for name in names:
        path = process_dir / name
        if path.is_file():
            return path
    return None


def _review_media(batch_dir: Path, item_dir: Path, artifact_name: str) -> Dict[str, str]:
    path = validated_promoted_artifact_path(item_dir, artifact_name)
    status = "已明确通过"
    if path is None:
        path = _review_candidate_path(item_dir, artifact_name)
        status = "待明确验收"
    if path is None:
        return {"url": "", "status": "尚无候选", "source_path": "", "sha256": ""}
    relative_item = path.relative_to(item_dir).as_posix()
    relative_batch = path.relative_to(batch_dir).as_posix()
    return {
        "url": quote(relative_batch),
        "status": status,
        "source_path": relative_item,
        "sha256": _sha256_file(path),
    }


def build_review_report(batch_dir: Path) -> Path:
    batch_dir = batch_dir.resolve()
    cards = []
    for item_dir in sorted(path for path in batch_dir.iterdir() if path.is_dir() and re.match(r"V\d{3}_", path.name)):
        video_id = item_dir.name.split("_", 1)[0]
        title_path = validated_promoted_artifact_path(item_dir, "标题.txt") or _review_candidate_path(item_dir, "标题.txt")
        title = title_path.read_text(encoding="utf-8") if title_path is not None else "标题尚无候选"
        task = read_json(read_compatible_path(item_dir, "任务状态", "任务信息.json"), {})
        auto_qa_path = read_compatible_path(item_dir, "验收记录", "自动验收报告.md")
        auto_qa = auto_qa_path.read_text(encoding="utf-8") if auto_qa_path.exists() else "尚无自动验收报告"
        video = _review_media(batch_dir, item_dir, "视频.mp4")
        cover = _review_media(batch_dir, item_dir, "封面图.png")
        video_tag = f'<video controls preload="metadata" src="{video["url"]}"></video>' if video["url"] else '<p class="missing">视频尚未下载</p>'
        cover_tag = f'<img src="{cover["url"]}" alt="{video_id} 封面">' if cover["url"] else ""
        video_evidence = html.escape(
            f'视频：{video["status"]}；候选：{video["source_path"] or "无"}；SHA-256：{video["sha256"] or "无"}'
        )
        cards.append(
            f'''<section class="video-card" data-video-id="{html.escape(video_id)}" data-video-source="{html.escape(video["source_path"])}" data-video-sha256="{html.escape(video["sha256"])}">
  <h2>{html.escape(video_id)}</h2>
  <div class="media">{video_tag}{cover_tag}</div>
  <p>{video_evidence}</p>
  <pre>{html.escape(title)}</pre>
  <p>task_id：{html.escape(str(task.get("task_id") or "未提交"))}</p>
  <details><summary>自动验收摘要</summary><pre>{html.escape(auto_qa)}</pre></details>
  <label><input type="radio" name="{video_id}" value="passed"> 通过</label>
  <label><input type="radio" name="{video_id}" value="failed"> 不通过</label>
  <label>不通过原因<textarea class="reason" rows="3"></textarea></label>
  <label>修改建议<textarea class="suggestion" rows="2"></textarea></label>
</section>'''
        )

    document = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>批次验收报告</title><style>
body{{font-family:"Microsoft YaHei",sans-serif;background:#f4f6f8;margin:0;padding:24px;color:#172033}}
main{{max-width:1100px;margin:auto}}.video-card{{background:white;border-radius:16px;padding:20px;margin:18px 0;box-shadow:0 6px 24px #18315318}}
.media{{display:flex;gap:16px;overflow:auto}}video,img{{max-height:480px;max-width:45%;border-radius:12px;background:#111}}
label{{display:block;margin:10px 0}}textarea{{display:block;width:100%;box-sizing:border-box;margin-top:6px}}button{{padding:12px 20px;border:0;border-radius:10px;background:#1467d8;color:white;font-weight:700}}pre{{white-space:pre-wrap}}
</style></head><body><main><h1>批次验收报告</h1>{''.join(cards)}
<button id="complete">完成验收并下载结果</button><p id="error"></p></main><script>
document.getElementById('complete').addEventListener('click',()=>{{
  const items=[]; let error='';
  document.querySelectorAll('.video-card').forEach(card=>{{
    const choice=card.querySelector('input[type=radio]:checked');
    const reason=card.querySelector('.reason').value.trim();
    if(!choice) error='每个视频都必须选择通过或不通过';
    if(choice && choice.value==='failed' && !reason) error='不通过的视频必须填写原因';
    items.push({{video_id:card.dataset.videoId,decision:choice?choice.value:'',reason,suggestion:card.querySelector('.suggestion').value.trim(),artifacts:{{'视频.mp4':{{source_path:card.dataset.videoSource,sha256:card.dataset.videoSha256}}}}}});
  }});
  if(error){{document.getElementById('error').textContent=error;return;}}
  const blob=new Blob([JSON.stringify({{completed_at:new Date().toISOString(),items}},null,2)],{{type:'application/json'}});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='批次验收结果.json';a.click();URL.revokeObjectURL(a.href);
}});
</script></body></html>'''
    output = batch_dir / "批次验收报告.html"
    atomic_write_text(output, document)
    return output


def record_review(batch_dir: Path, result_path: Path, knowledge_dir: Path) -> None:
    result = read_json(result_path)
    items = result.get("items", [])
    if not items:
        raise ValueError("验收结果没有视频项目")
    for decision in items:
        if decision.get("decision") not in {"passed", "failed"}:
            raise ValueError("每个视频都必须选择通过或不通过")
        if decision["decision"] == "failed" and not str(decision.get("reason", "")).strip():
            raise ValueError("不通过的视频必须填写原因")
    atomic_write_json(batch_dir / "批次验收结果.json", result)
    markdown = ["# 批次验收结果", ""]
    candidates_dir = knowledge_dir.resolve() / "候选经验"
    for decision in items:
        item_dir = _find_item(batch_dir, decision["video_id"])
        item_md = (
            f"# 人工验收结果\n\n结果：{decision['decision']}\n\n"
            f"原因：{decision.get('reason', '')}\n\n建议：{decision.get('suggestion', '')}\n"
        )
        atomic_write_text(work_path(item_dir, "验收记录", "人工验收结果.md"), item_md)
        markdown.append(f"- {decision['video_id']}：{decision['decision']}；{decision.get('reason', '')}")
        if decision["decision"] == "failed":
            candidate_id = f"{decision['video_id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            atomic_write_json(
                candidates_dir / f"{candidate_id}.json",
                {
                    "candidate_id": candidate_id,
                    "status": "candidate",
                    "video_id": decision["video_id"],
                    "issue": decision["reason"],
                    "suggestion": decision.get("suggestion", ""),
                    "created_at": datetime.now().astimezone().isoformat(),
                    "promotion_rule": "仅在重跑通过且学习模式获得用户确认后转为正式规则",
                },
            )
    atomic_write_text(batch_dir / "批次验收结果.md", "\n".join(markdown) + "\n")


def _parse_points(values: Iterable[str]) -> Tuple[str, ...]:
    points: List[str] = []
    for value in values:
        points.extend(part.strip() for part in value.split("|") if part.strip())
    return tuple(points)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="产品视频技能包便携工作流工具（不直接生成付费内容）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="创建批次、启动确认单和独立视频目录")
    init.add_argument("--product-dir", type=Path, required=True)
    init.add_argument("--product-name", required=True)
    init.add_argument("--selling-point", action="append", required=True, help="可重复；也可用 | 分隔")
    init.add_argument("--total", type=int, required=True)
    init.add_argument("--mode", choices=("learning", "auto"), required=True)
    init.add_argument("--resolution", choices=("768P", "2K"), default="768P")
    init.add_argument("--max-budget", required=True)
    init.add_argument("--cover-reference-dir", type=Path, required=True)
    init.add_argument("--knowledge-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")

    validate = subparsers.add_parser("validate-content", help="校验并保存一条结构化策划内容")
    validate.add_argument("--item-dir", type=Path, required=True)
    validate.add_argument("--content", type=Path, required=True)
    validate.add_argument("--profile", type=Path, required=True)

    review = subparsers.add_parser("build-review", help="生成离线批次验收报告")
    review.add_argument("--batch", type=Path, required=True)

    task = subparsers.add_parser("record-task", help="立即记录 AutoDL task_id")
    task.add_argument("--batch", type=Path, required=True)
    task.add_argument("--video-id", required=True)
    task.add_argument("--task-id", required=True)
    task.add_argument("--request-id")
    task.add_argument("--request-hash")
    task.add_argument("--estimated-cost")

    record = subparsers.add_parser("record-review", help="回写验收结果并形成候选经验")
    record.add_argument("--batch", type=Path, required=True)
    record.add_argument("--result", type=Path, required=True)
    record.add_argument("--knowledge-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")

    organize = subparsers.add_parser("organize", help="安全整理单条任务目录的工作文件")
    organize_target = organize.add_mutually_exclusive_group(required=True)
    organize_target.add_argument("--item-dir", type=Path)
    organize_target.add_argument("--batch", type=Path)
    organize.add_argument("--dry-run", action="store_true")

    output_review = subparsers.add_parser("review-output", help="记录单项产出验收决定并按规则晋升或撤下")
    output_review.add_argument("--item-dir", type=Path, required=True)
    output_review.add_argument("--artifact", choices=sorted(DELIVERABLE_NAMES), required=True)
    output_review.add_argument("--source", type=Path, required=True)
    output_review.add_argument("--decision", choices=sorted(APPROVAL_DECISIONS), required=True)
    output_review.add_argument("--confirmed-by", required=True)
    output_review.add_argument("--feedback", required=True)

    output_audit = subparsers.add_parser("audit-outputs", help="审计并撤下没有明确通过证据的一级产出")
    output_audit_target = output_audit.add_mutually_exclusive_group(required=True)
    output_audit_target.add_argument("--item-dir", type=Path)
    output_audit_target.add_argument("--batch", type=Path)
    output_audit.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            context = initialize_batch(
                product_dir=args.product_dir,
                product_name=args.product_name,
                selling_points=_parse_points(args.selling_point),
                total_videos=args.total,
                run_mode=args.mode,
                resolution=args.resolution,
                max_budget_yuan=args.max_budget,
                cover_reference_dir=args.cover_reference_dir,
                knowledge_dir=args.knowledge_dir,
            )
            print(context.batch_dir)
        elif args.command == "validate-content":
            save_content_package(args.item_dir, args.content, args.profile)
            print("内容校验通过并已落盘")
        elif args.command == "build-review":
            print(build_review_report(args.batch))
        elif args.command == "record-task":
            record_task(
                args.batch,
                args.video_id,
                args.task_id,
                request_id=args.request_id,
                request_hash=args.request_hash,
                estimated_cost_yuan=args.estimated_cost,
            )
            print("task_id 已记录")
        elif args.command == "record-review":
            record_review(args.batch, args.result, args.knowledge_dir)
            print("验收结果已回写，失败项已进入候选经验")
        elif args.command == "organize":
            result = (
                organize_item_dir(args.item_dir, dry_run=args.dry_run)
                if args.item_dir is not None
                else organize_batch_dir(args.batch, dry_run=args.dry_run)
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "review-output":
            event = record_artifact_decision(
                args.item_dir,
                args.artifact,
                args.source,
                args.decision,
                args.confirmed_by,
                args.feedback,
            )
            if args.decision == "passed":
                result = {"event": event, "promoted": str(promote_approved_artifact(args.item_dir, event))}
            else:
                result = {"event": event, "audit": audit_promoted_outputs(args.item_dir)}
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "audit-outputs":
            result = (
                audit_promoted_outputs(args.item_dir, dry_run=args.dry_run)
                if args.item_dir is not None
                else audit_batch_outputs(args.batch, dry_run=args.dry_run)
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if _audit_result_has_errors(result):
                return 2
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
