#!/usr/bin/env python3

import hashlib
import importlib.util
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
