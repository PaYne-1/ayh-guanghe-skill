#!/usr/bin/env python3

import importlib.util
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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
