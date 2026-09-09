# Product Video Low-Cost Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `product-video-pipeline` into a resumable script-driven batch workflow that uses GPT Web for unreviewed images and minimizes DeepSeek calls while preserving payment and final-video approval gates.

**Architecture:** Add a compact versioned policy and a Python state-machine runner above the existing `workflow_cli.py` and `autodl_h3.py`. The runner performs deterministic work locally and emits compact external actions only for batch content generation, GPT Web image generation, user approvals, and final review; all state is atomically persisted so execution resumes without repeating completed or paid work.

**Tech Stack:** Python 3 standard library, Pillow, pytest, existing `workflow_cli.py`, existing `autodl_h3.py`, GPT Web through the host agent browser tool, ffprobe when available.

## Global Constraints

- Preserve all pre-existing uncommitted edits; inspect `git diff -- <file>` before modifying every existing file and apply only incremental patches.
- GPT Web is the only image-generation channel for storyboard, last frame, and cover.
- Images receive no human approval and no model-based visual review.
- Local image checks remain mandatory: decodable non-empty file, allowed format, 9:16, normalized `2160×3840`, SHA-256, task-local path, and distinct storyboard/last-frame hashes.
- A `1152×2048` 9:16 GPT Web result may be resized deterministically to `2160×3840`; non-9:16 input must not be stretched, cropped, inpainted, or overlaid with text.
- Startup budget approval authorizes all V01 submissions within the confirmed total budget; V02 always requires a separate user authorization; V03 is forbidden.
- Final video approval remains a user decision.
- Polling, downloading, hashing, resizing, promotion, auditing, and state updates must not invoke DeepSeek.
- Unknown paid-submit status must never be automatically resubmitted.
- Existing batch layout, seven root deliverables, approval-event format, request hash, task ID, and legacy CLI commands remain compatible.
- Normal execution returns compact JSON; full diagnostic logs remain on disk and are not copied into model context.
- No live paid API call is permitted during tests or dry-run verification.

---

### Task 1: Add the compact runtime policy

**Files:**
- Create: `skill-package/product-video-pipeline/pipeline_policy.json`
- Create: `skill-package/product-video-pipeline/scripts/pipeline_policy.py`
- Modify: `tests/test_portable_skill_package.py`

**Interfaces:**
- Produces: `load_policy(skill_root: Path) -> dict[str, object]`
- Produces: `policy_digest(policy: Mapping[str, object]) -> str`
- Produces policy keys `version`, `image`, `approvals`, `model_budget`, `autodl`, and `states` for later tasks.

- [ ] **Step 1: Add failing policy tests**

Append to `tests/test_portable_skill_package.py`:

```python
def test_compact_pipeline_policy_is_versioned_and_web_only():
    policy = json.loads((SKILL_ROOT / "pipeline_policy.json").read_text(encoding="utf-8"))
    assert policy["version"] == 1
    assert policy["image"] == {
        "provider": "gpt_web",
        "human_review": False,
        "model_visual_review": False,
        "target_width": 2160,
        "target_height": 3840,
        "download_retries": 1,
    }
    assert policy["approvals"] == {
        "startup_budget": True,
        "v01_within_budget": "automatic",
        "v02": "user_required",
        "final_video": "user_required",
    }
    assert policy["model_budget"]["per_video"] == 6


def test_policy_digest_is_stable_for_key_order():
    runtime = load_script("pipeline_policy.py")
    left = {"b": 2, "a": 1}
    right = {"a": 1, "b": 2}
    assert runtime.policy_digest(left) == runtime.policy_digest(right)
```

- [ ] **Step 2: Run the tests and verify failure**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "compact_pipeline_policy or policy_digest" -v
```

Expected: FAIL because `pipeline_policy.json` and `pipeline_policy.py` do not exist.

- [ ] **Step 3: Create the compact policy**

Create `skill-package/product-video-pipeline/pipeline_policy.json`:

```json
{
  "version": 1,
  "image": {
    "provider": "gpt_web",
    "human_review": false,
    "model_visual_review": false,
    "target_width": 2160,
    "target_height": 3840,
    "download_retries": 1
  },
  "approvals": {
    "startup_budget": true,
    "v01_within_budget": "automatic",
    "v02": "user_required",
    "final_video": "user_required"
  },
  "model_budget": {
    "per_video": 6,
    "batch_content_calls": 1
  },
  "autodl": {
    "workflow_id": "minimax_h3_lightx2v_v5_15s",
    "duration_seconds": 15,
    "poll_interval_seconds": 20,
    "poll_timeout_seconds": 3600
  },
  "states": [
    "WAITING_START_APPROVAL",
    "RUNNING_AUTOMATICALLY",
    "WAITING_PAID_APPROVAL",
    "GENERATING",
    "WAITING_FINAL_REVIEW",
    "WAITING_RERUN_APPROVAL",
    "COMPLETED",
    "BLOCKED"
  ]
}
```

Create `skill-package/product-video-pipeline/scripts/pipeline_policy.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def policy_digest(policy: Mapping[str, object]) -> str:
    encoded = json.dumps(
        policy, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_policy(skill_root: Path) -> dict[str, Any]:
    policy_path = skill_root / "pipeline_policy.json"
    value = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("pipeline_policy.json 版本无效")
    if value.get("image", {}).get("provider") != "gpt_web":
        raise ValueError("图片渠道必须固定为 gpt_web")
    return value
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "compact_pipeline_policy or policy_digest" -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit the policy unit**

```powershell
git add -- skill-package/product-video-pipeline/pipeline_policy.json skill-package/product-video-pipeline/scripts/pipeline_policy.py tests/test_portable_skill_package.py
git commit -m "feat: add compact product video runtime policy"
```

---

### Task 2: Build atomic resumable batch state

**Files:**
- Create: `skill-package/product-video-pipeline/scripts/pipeline_runner.py`
- Modify: `tests/test_portable_skill_package.py`

**Interfaces:**
- Consumes: `load_policy(skill_root: Path)` and `policy_digest(policy)` from Task 1.
- Produces: `RunnerState` dataclass.
- Produces: `load_or_create_state(batch_dir: Path, policy: dict[str, object]) -> RunnerState`.
- Produces: `save_state(batch_dir: Path, state: RunnerState) -> Path`.
- Produces: `transition(state: RunnerState, target: str, *, reason: str = "") -> RunnerState`.
- Persists: `批次目录/流水线状态.json`.

- [ ] **Step 1: Add failing state tests**

Append:

```python
def test_runner_state_is_atomic_and_resumable(tmp_path):
    policy_module = load_script("pipeline_policy.py")
    runner = load_script("pipeline_runner.py")
    policy = policy_module.load_policy(SKILL_ROOT)
    batch = tmp_path / "20260907_批次001"
    batch.mkdir()

    state = runner.load_or_create_state(batch, policy)
    assert state.status == "WAITING_START_APPROVAL"
    assert state.policy_digest == policy_module.policy_digest(policy)

    runner.transition(state, "RUNNING_AUTOMATICALLY", reason="预算已确认")
    runner.save_state(batch, state)
    restored = runner.load_or_create_state(batch, policy)

    assert restored.status == "RUNNING_AUTOMATICALLY"
    assert restored.history[-1]["reason"] == "预算已确认"
    assert not (batch / "流水线状态.json.tmp").exists()


def test_runner_rejects_unknown_state(tmp_path):
    runner = load_script("pipeline_runner.py")
    state = runner.RunnerState.new("digest")
    with pytest.raises(ValueError, match="未知状态"):
        runner.transition(state, "DO_WHATEVER")
```

- [ ] **Step 2: Verify the tests fail**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "runner_state or runner_rejects_unknown_state" -v
```

Expected: FAIL because `pipeline_runner.py` is absent.

- [ ] **Step 3: Implement state persistence and transitions**

Create the first implementation in `pipeline_runner.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import importlib.util
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    pending_action: dict[str, Any] | None = None
    blocked_reason: str = ""
    history: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def new(cls, digest: str) -> "RunnerState":
        return cls(1, digest, "WAITING_START_APPROVAL")


def save_state(batch_dir: Path, state: RunnerState) -> Path:
    path = batch_dir.resolve() / STATE_FILENAME
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)
    return path


def load_or_create_state(batch_dir: Path, policy: dict[str, object]) -> RunnerState:
    path = batch_dir.resolve() / STATE_FILENAME
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
```

- [ ] **Step 4: Run state tests**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "runner_state or runner_rejects_unknown_state" -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit resumable state**

```powershell
git add -- skill-package/product-video-pipeline/scripts/pipeline_runner.py tests/test_portable_skill_package.py
git commit -m "feat: add resumable product video state machine"
```

---

### Task 3: Normalize and automatically promote GPT Web images

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/pipeline_runner.py`
- Modify: `tests/test_portable_skill_package.py`

**Interfaces:**
- Consumes existing `workflow_cli.record_artifact_decision()` and `workflow_cli.promote_approved_artifact()`.
- Produces: `normalize_web_image(source: Path, output: Path, *, width: int = 2160, height: int = 3840) -> dict[str, object]`.
- Produces: `accept_web_image(item_dir: Path, artifact_name: str, source: Path) -> dict[str, object]`.
- Supported artifacts: `分镜图.png`, `尾帧图.png`, `封面图.png`.

- [ ] **Step 1: Add failing image tests**

Append:

```python
def test_web_image_is_normalized_and_auto_promoted(tmp_path):
    runner = load_script("pipeline_runner.py")
    item = tmp_path / "V001_卖点_待生成"
    raw = tmp_path / "gpt-result.png"
    Image.new("RGB", (1152, 2048), "navy").save(raw)

    result = runner.accept_web_image(item, "分镜图.png", raw)

    promoted = item / "分镜图.png"
    assert result["ok"] is True
    assert result["review"] == "skipped_by_policy"
    assert result["provider"] == "gpt_web"
    assert Image.open(promoted).size == (2160, 3840)
    events = json.loads(
        (item / "_工作文件" / "验收记录" / "产出验收记录.json").read_text(encoding="utf-8")
    )
    assert events[-1]["confirmed_by"] == "batch-auto-authorization"


def test_web_image_rejects_non_nine_sixteen_without_crop(tmp_path):
    runner = load_script("pipeline_runner.py")
    source = tmp_path / "square.png"
    Image.new("RGB", (1024, 1024), "white").save(source)
    with pytest.raises(ValueError, match="9:16"):
        runner.normalize_web_image(source, tmp_path / "normalized.png")


def test_storyboard_and_last_frame_must_have_distinct_hashes(tmp_path):
    runner = load_script("pipeline_runner.py")
    item = tmp_path / "V001_卖点_待生成"
    source = tmp_path / "same.png"
    Image.new("RGB", (1152, 2048), "green").save(source)
    runner.accept_web_image(item, "分镜图.png", source)
    with pytest.raises(ValueError, match="尾帧不得与分镜相同"):
        runner.accept_web_image(item, "尾帧图.png", source)
```

- [ ] **Step 2: Verify the image tests fail**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "web_image or storyboard_and_last_frame" -v
```

Expected: FAIL because the image functions are undefined.

- [ ] **Step 3: Implement deterministic image handling**

Add imports and functions to `pipeline_runner.py`:

```python
import hashlib
import importlib.util

from PIL import Image


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
    source = source.resolve()
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError("GPT 网页图片不存在或为空")
    with Image.open(source) as image:
        image.load()
        source_size = image.size
        if image.width * 16 != image.height * 9:
            raise ValueError("GPT 网页图片必须为 9:16，禁止自动裁切或拉伸")
        normalized = image.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        normalized.save(temporary, format="PNG")
        temporary.replace(output)
    return {
        "source_size": list(source_size),
        "target_size": [width, height],
        "sha256": _sha256(output),
    }


def accept_web_image(item_dir: Path, artifact_name: str, source: Path) -> dict[str, object]:
    if artifact_name not in {"分镜图.png", "尾帧图.png", "封面图.png"}:
        raise ValueError(f"不支持的图片产出：{artifact_name}")
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
```

- [ ] **Step 4: Run focused image and existing approval tests**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "web_image or storyboard_and_last_frame or approval_events or artifact_decision" -v
```

Expected: all selected tests PASS.

- [ ] **Step 5: Commit image automation**

```powershell
git add -- skill-package/product-video-pipeline/scripts/pipeline_runner.py tests/test_portable_skill_package.py
git commit -m "feat: auto-promote GPT Web image results"
```

---

### Task 4: Emit compact external actions and enforce model-call budgets

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/pipeline_runner.py`
- Modify: `tests/test_portable_skill_package.py`

**Interfaces:**
- Produces: `ExternalAction` dataclass with `kind`, `video_id`, `artifact`, `prompt_path`, `output_path`, and `reason`.
- Produces: `consume_model_call(state: RunnerState, policy: dict[str, object], *, video_id: str | None) -> None`.
- Produces: `accept_batch_content(batch_dir: Path, content_dir: Path, profile_path: Path) -> dict[str, object]`.
- Produces: `record_image_failure(state: RunnerState, *, video_id: str, artifact: str, reason: str) -> dict[str, object]`.
- Produces: `next_action(batch_dir: Path, state: RunnerState, policy: dict[str, object]) -> dict[str, object]`.
- Emits action kinds `USER_START_APPROVAL_REQUIRED`, `BATCH_CONTENT_REQUIRED`, `GPT_WEB_IMAGE_REQUIRED`, `USER_RERUN_APPROVAL_REQUIRED`, `USER_FINAL_REVIEW_REQUIRED`, `BLOCKED`, and `DONE`.

- [ ] **Step 1: Add failing compact-action and budget tests**

Append:

```python
def test_model_budget_blocks_only_model_dependent_work():
    policy = json.loads((SKILL_ROOT / "pipeline_policy.json").read_text(encoding="utf-8"))
    runner = load_script("pipeline_runner.py")
    state = runner.RunnerState.new("digest")
    state.model_calls_by_video["V001"] = policy["model_budget"]["per_video"]
    with pytest.raises(runner.ModelBudgetExceeded, match="V001"):
        runner.consume_model_call(state, policy, video_id="V001")


def test_next_image_action_is_compact_and_web_only(tmp_path):
    runner = load_script("pipeline_runner.py")
    policy = json.loads((SKILL_ROOT / "pipeline_policy.json").read_text(encoding="utf-8"))
    batch = tmp_path / "batch"
    item = batch / "V001_卖点_待生成"
    process = item / "_工作文件" / "生成过程"
    process.mkdir(parents=True)
    (process / "分镜提示词.txt").write_text("生成轮椅分镜", encoding="utf-8")
    state = runner.RunnerState.new("digest")
    state.status = "RUNNING_AUTOMATICALLY"

    action = runner.next_action(batch, state, policy)

    assert action == {
        "kind": "GPT_WEB_IMAGE_REQUIRED",
        "video_id": "V001",
        "artifact": "分镜图.png",
        "prompt_path": str((process / "分镜提示词.txt").resolve()),
        "output_path": str((process / "GPT网页原始分镜.png").resolve()),
    }
    assert "prompt" not in action


def test_second_image_technical_failure_blocks_the_item():
    runner = load_script("pipeline_runner.py")
    state = runner.RunnerState.new("digest")
    first = runner.record_image_failure(
        state, video_id="V001", artifact="分镜图.png", reason="下载为空"
    )
    second = runner.record_image_failure(
        state, video_id="V001", artifact="分镜图.png", reason="仍然为空"
    )
    assert first["kind"] == "RETRY_GPT_WEB_IMAGE"
    assert first["attempt"] == 2
    assert second["kind"] == "BLOCKED"
    assert state.status == "BLOCKED"


def test_batch_content_is_accepted_in_one_deterministic_operation(tmp_path, monkeypatch):
    runner = load_script("pipeline_runner.py")
    batch = tmp_path / "batch"
    (batch / "V001_甲_待生成").mkdir(parents=True)
    (batch / "V002_乙_待生成").mkdir(parents=True)
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    for video_id in ("V001", "V002"):
        (content_dir / f"{video_id}.json").write_text("{}", encoding="utf-8")
    calls = []
    fake_workflow = type("Workflow", (), {"save_content_package": staticmethod(lambda item, content, profile: calls.append((item, content, profile)))})
    monkeypatch.setattr(runner, "_load_workflow_cli", lambda: fake_workflow)

    result = runner.accept_batch_content(batch, content_dir, tmp_path / "profile.json")

    assert result == {"ok": True, "accepted": ["V001", "V002"]}
    assert len(calls) == 2
```

- [ ] **Step 2: Verify tests fail**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "model_budget or next_image_action" -v
```

Expected: FAIL because the action and budget interfaces do not exist.

- [ ] **Step 3: Implement compact actions and counters**

Add to `pipeline_runner.py`:

```python
class ModelBudgetExceeded(RuntimeError):
    pass


def consume_model_call(
    state: RunnerState, policy: dict[str, object], *, video_id: str | None
) -> None:
    limits = policy["model_budget"]
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
    return sorted(path for path in batch_dir.iterdir() if path.is_dir() and path.name.startswith("V"))


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
```

- [ ] **Step 4: Run focused action tests**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "model_budget or next_image_action" -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit external-action protocol**

```powershell
git add -- skill-package/product-video-pipeline/scripts/pipeline_runner.py tests/test_portable_skill_package.py
git commit -m "feat: add compact external action protocol"
```

---

### Task 5: Run AutoDL submission, polling, and download without model turns

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/pipeline_runner.py`
- Modify: `skill-package/product-video-pipeline/scripts/autodl_h3.py`
- Modify: `skill-package/product-video-pipeline/scripts/workflow_cli.py`
- Modify: `tests/test_portable_skill_package.py`

**Interfaces:**
- Consumes existing `autodl_h3.submit_payload()`, `poll_task()`, `first_result_url()`, and `download_atomic()`.
- Produces: `run_autodl_item(batch_dir: Path, item_dir: Path, state: RunnerState, *, api_key: str | None = None, dry_run: bool = False) -> dict[str, object]`.
- Produces: `validate_video_file(path: Path, expected_resolution: str) -> dict[str, object]`.
- Never invokes a model and never resubmits an existing `task_id` or request hash.

- [ ] **Step 1: Add failing deterministic AutoDL tests**

Append:

```python
def test_runner_poll_and_download_do_not_increment_model_calls(tmp_path, monkeypatch):
    runner = load_script("pipeline_runner.py")
    batch = tmp_path / "batch"
    item = batch / "V001_卖点_待生成"
    state_dir = item / "_工作文件" / "任务状态"
    process = item / "_工作文件" / "生成过程"
    process.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    (state_dir / "提交请求.json").write_text(
        json.dumps({
            "prompt": "一镜到底，连续平稳运镜，完整双人对话口播",
            "duration": 15,
            "resolution": "768p竖",
            "first_frame": "data:image/png;base64,AAAA",
            "last_frame": "data:image/png;base64,BBBB",
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    state = runner.RunnerState.new("digest")
    state.model_calls_by_video["V001"] = 2

    monkeypatch.setattr(runner, "_submit_item", lambda *a, **k: {"task_id": "task-1", "request_hash": "hash-1"})
    monkeypatch.setattr(runner, "_poll_item", lambda *a, **k: {"status": "completed", "url": "https://example.invalid/video.mp4"})
    monkeypatch.setattr(runner, "_download_item", lambda *a, **k: process / "视频候选.mp4")
    monkeypatch.setattr(runner, "validate_video_file", lambda *a, **k: {"ok": True})

    result = runner.run_autodl_item(batch, item, state, api_key="test", dry_run=False)

    assert result["ok"] is True
    assert state.model_calls_by_video["V001"] == 2


def test_existing_task_id_prevents_second_paid_submit(tmp_path, monkeypatch):
    runner = load_script("pipeline_runner.py")
    batch = tmp_path / "batch"
    item = batch / "V001_卖点_待生成"
    state_dir = item / "_工作文件" / "任务状态"
    state_dir.mkdir(parents=True)
    (state_dir / "任务信息.json").write_text(
        json.dumps({"video_id": "V001", "task_id": "existing-task"}), encoding="utf-8"
    )
    monkeypatch.setattr(runner, "_submit_item", lambda *a, **k: pytest.fail("must not submit"))

    result = runner.run_autodl_item(batch, item, runner.RunnerState.new("digest"), api_key="test")

    assert result["resumed_task_id"] == "existing-task"


def test_paid_v01_requires_confirmed_total_within_budget(tmp_path):
    runner = load_script("pipeline_runner.py")
    state = runner.RunnerState.new("digest")
    state.status = "RUNNING_AUTOMATICALLY"
    state.approved_budget = "10.00"
    state.estimated_v01_total = "12.00"
    with pytest.raises(PermissionError, match="超过批准预算"):
        runner.assert_paid_submit_allowed(state, {"retry_count": 0}, "V001")


def test_v02_requires_separate_video_authorization():
    runner = load_script("pipeline_runner.py")
    state = runner.RunnerState.new("digest")
    state.status = "RUNNING_AUTOMATICALLY"
    with pytest.raises(PermissionError, match="V02 单独付费授权"):
        runner.assert_paid_submit_allowed(state, {"retry_count": 1}, "V001")
    state.rerun_budget_by_video["V001"] = "3.00"
    runner.assert_paid_submit_allowed(state, {"retry_count": 1}, "V001")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "poll_and_download or second_paid_submit" -v
```

Expected: FAIL because the runner AutoDL interface is missing.

- [ ] **Step 3: Add compact AutoDL status helpers**

Add a public status helper to `autodl_h3.py` so the runner does not duplicate response parsing:

```python
def task_status(response: Dict[str, object]) -> str:
    return _status(response)
```

Add `from decimal import Decimal`, then add runner adapters and orchestration to `pipeline_runner.py`:

```python
def _load_autodl():
    path = Path(__file__).with_name("autodl_h3.py")
    spec = importlib.util.spec_from_file_location("product_video_autodl_h3", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 autodl_h3.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _task_info(item_dir: Path) -> dict[str, object]:
    path = item_dir / "_工作文件" / "任务状态" / "任务信息.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _submit_item(item_dir: Path, api_key: str | None, dry_run: bool) -> dict[str, object]:
    autodl = _load_autodl()
    payload = item_dir / "_工作文件" / "任务状态" / "提交请求.json"
    return autodl.submit_payload(
        payload,
        api_key=api_key,
        dry_run=dry_run,
        confirm_paid=not dry_run,
        workflow_id=autodl.WORKFLOW_ID,
    )


def _poll_item(task_id: str, api_key: str | None) -> dict[str, object]:
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


def run_autodl_item(
    batch_dir: Path,
    item_dir: Path,
    state: RunnerState,
    *,
    api_key: str | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    video_id = item_dir.name.split("_", 1)[0]
    info = _task_info(item_dir)
    task_id = str(info.get("task_id") or "")
    submitted: dict[str, object] = {}
    if not task_id:
        if not dry_run:
            assert_paid_submit_allowed(state, info, video_id)
        submitted = _submit_item(item_dir, api_key, dry_run)
        if dry_run:
            return {"ok": True, "dry_run": True, "request_hash": submitted["request_hash"]}
        task_id = str(submitted["task_id"])
        workflow = _load_workflow_cli()
        workflow.record_task(
            batch_dir,
            video_id,
            task_id,
            request_id=submitted.get("request_id"),
            request_hash=submitted.get("request_hash"),
        )
    polled = _poll_item(task_id, api_key)
    if polled["status"] not in {"success", "succeeded", "completed"}:
        return {"ok": False, "task_id": task_id, "status": polled["status"]}
    candidate = _download_item(str(polled["url"]), item_dir)
    technical = validate_video_file(candidate, str(info.get("resolution", "768P")))
    return {
        "ok": bool(technical["ok"]),
        "task_id": task_id,
        "resumed_task_id": task_id if not submitted else "",
        "candidate": str(candidate.resolve()),
        "technical": technical,
    }


def assert_paid_submit_allowed(
    state: RunnerState, task_info: dict[str, object], video_id: str
) -> None:
    if state.status not in {"RUNNING_AUTOMATICALLY", "GENERATING"}:
        raise PermissionError("当前状态不允许付费提交")
    retry_count = int(task_info.get("retry_count", 0))
    if retry_count == 0:
        if not state.approved_budget or not state.estimated_v01_total:
            raise PermissionError("缺少 V01 批次预算授权或预计总价")
        if Decimal(state.estimated_v01_total) > Decimal(state.approved_budget):
            raise PermissionError("V01 预计总价超过批准预算")
        return
    if retry_count == 1 and video_id not in state.rerun_budget_by_video:
        raise PermissionError(f"{video_id} 缺少 V02 单独付费授权")
    if retry_count > 1:
        raise PermissionError("禁止提交 V03")
```

Update `workflow_cli.start_rerun()` immediately before it writes the V02 state so a V02 run cannot accidentally resume the V01 task ID:

```python
    previous_submission = {
        key: task.get(key)
        for key in ("task_id", "request_id", "request_hash", "estimated_cost_yuan")
        if task.get(key) is not None
    }
    if previous_submission:
        task.setdefault("submission_history", []).append(
            {"version": "V01", **previous_submission}
        )
    task.update(
        {
            "task_id": None,
            "request_id": None,
            "request_hash": None,
            "estimated_cost_yuan": None,
        }
    )
```

In the existing `test_start_rerun_allows_only_v02_and_updates_batch_table`, replace its `task` fixture with:

```python
task = {
    "video_id": "V001",
    "retry_count": 0,
    "status": "REVIEW_FAILED",
    "task_id": "v01-task",
    "request_id": "v01-request",
    "request_hash": "v01-hash",
    "estimated_cost_yuan": "3.00",
}
```

Then extend its assertions:

```python
assert updated["task_id"] is None
assert updated["request_hash"] is None
assert updated["submission_history"][-1]["version"] == "V01"
```

Add `import subprocess` and implement `validate_video_file()` with one argument-list `ffprobe` invocation:

```python
def validate_video_file(path: Path, expected_resolution: str) -> dict[str, object]:
    path = path.resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("视频候选不存在或为空")
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(path),
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
```

- [ ] **Step 4: Run AutoDL unit tests and the existing dry-run tests**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "poll_and_download or second_paid_submit or autodl or dry_run or task_id" -v
```

Expected: all selected tests PASS and no network request occurs.

- [ ] **Step 5: Commit deterministic video execution**

```powershell
git add -- skill-package/product-video-pipeline/scripts/pipeline_runner.py skill-package/product-video-pipeline/scripts/autodl_h3.py skill-package/product-video-pipeline/scripts/workflow_cli.py tests/test_portable_skill_package.py
git commit -m "feat: run video submit polling and download without model turns"
```

---

### Task 6: Add the runner CLI and end-to-end dry-run workflow

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/pipeline_runner.py`
- Modify: `skill-package/product-video-pipeline/scripts/self_test.py`
- Modify: `tests/test_portable_skill_package.py`

**Interfaces:**
- Produces CLI commands `status`, `approve-start`, `next`, `accept-content`, `accept-image`, `image-failed`, `run-local`, `approve-rerun`, and `complete-review`.
- `next` and `run-local` print one compact JSON object.
- `accept-image` accepts an already-downloaded GPT Web image and performs no network or model call.

- [ ] **Step 1: Add failing CLI tests**

Append:

```python
def test_runner_cli_returns_one_compact_json_action(tmp_path):
    batch = tmp_path / "batch"
    batch.mkdir()
    result = subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts" / "pipeline_runner.py"), "next", "--batch", str(batch)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    action = json.loads(result.stdout)
    assert action == {"kind": "USER_START_APPROVAL_REQUIRED"}
    assert len(result.stdout) < 512


def test_runner_help_exposes_only_supported_commands():
    result = subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts" / "pipeline_runner.py"), "--help"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    for command in ("status", "approve-start", "next", "accept-content", "accept-image", "image-failed", "run-local", "approve-rerun", "complete-review"):
        assert command in result.stdout
```

- [ ] **Step 2: Verify CLI tests fail**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "runner_cli or runner_help" -v
```

Expected: FAIL because the runner has no CLI parser.

- [ ] **Step 3: Implement the CLI parser and compact output**

Add to `pipeline_runner.py`:

```python
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
    image.add_argument("--artifact", choices=("分镜图.png", "尾帧图.png", "封面图.png"), required=True)
    image.add_argument("--source", type=Path, required=True)
    image_failed = sub.add_parser("image-failed")
    image_failed.add_argument("--batch", type=Path, required=True)
    image_failed.add_argument("--video-id", required=True)
    image_failed.add_argument("--artifact", choices=("分镜图.png", "尾帧图.png", "封面图.png"), required=True)
    image_failed.add_argument("--reason", required=True)
    rerun = sub.add_parser("approve-rerun")
    rerun.add_argument("--batch", type=Path, required=True)
    rerun.add_argument("--video-id", required=True)
    rerun.add_argument("--approved-cost", required=True)
    review = sub.add_parser("complete-review")
    review.add_argument("--batch", type=Path, required=True)
    review.add_argument("--result", type=Path, required=True)
    review.add_argument("--knowledge-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    return parser
```

Add `import argparse` and `from decimal import Decimal`. Load the policy through `_load_policy_module()` in the command dispatcher:

```python
def _find_item_dir(batch_dir: Path, video_id: str) -> Path:
    matches = [path for path in _video_items(batch_dir) if path.name.split("_", 1)[0] == video_id]
    if len(matches) != 1:
        raise ValueError(f"无法唯一定位视频项目：{video_id}")
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    skill_root = Path(__file__).resolve().parents[1]
    policy = _load_policy_module().load_policy(skill_root)
    batch = args.batch.resolve()
    state = load_or_create_state(batch, policy)
    workflow = _load_workflow_cli()
    try:
        if args.command == "status":
            result = {"status": state.status, "pending_action": state.pending_action}
        elif args.command == "next":
            result = next_action(batch, state, policy)
        elif args.command == "approve-start":
            approved = Decimal(args.approved_budget)
            estimated = Decimal(args.estimated_v01_total)
            if approved <= 0:
                raise ValueError("批准预算必须大于 0")
            if estimated <= 0 or estimated > approved:
                raise ValueError("V01 预计总价必须大于 0 且不超过批准预算")
            state.approved_budget = str(approved)
            state.estimated_v01_total = str(estimated)
            transition(state, "RUNNING_AUTOMATICALLY", reason="V01 总预算已确认")
            save_state(batch, state)
            result = next_action(batch, state, policy)
        elif args.command == "accept-content":
            consume_model_call(state, policy, video_id=None)
            result = accept_batch_content(batch, args.content_dir.resolve(), args.profile.resolve())
            save_state(batch, state)
        elif args.command == "accept-image":
            item = _find_item_dir(batch, args.video_id)
            consume_model_call(state, policy, video_id=args.video_id)
            result = accept_web_image(item, args.artifact, args.source)
            save_state(batch, state)
        elif args.command == "image-failed":
            consume_model_call(state, policy, video_id=args.video_id)
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
            rerun_cost = Decimal(args.approved_cost)
            if rerun_cost <= 0:
                raise ValueError("V02 批准费用必须大于 0")
            workflow.start_rerun(batch, args.video_id)
            state.rerun_budget_by_video[args.video_id] = str(rerun_cost)
            transition(state, "RUNNING_AUTOMATICALLY", reason=f"{args.video_id} V02 已获授权")
            save_state(batch, state)
            result = next_action(batch, state, policy)
        elif args.command == "complete-review":
            workflow.record_review(batch, args.result, args.knowledge_dir)
            audit = workflow.audit_batch_outputs(batch)
            if workflow._audit_result_has_errors(audit):
                transition(state, "BLOCKED", reason="最终七项产出审计失败")
                result = {"kind": "BLOCKED", "reason": state.blocked_reason}
            else:
                transition(state, "COMPLETED", reason="最终视频验收及七项产出审计通过")
                result = {"kind": "DONE"}
            save_state(batch, state)
        else:
            raise ValueError(f"未知命令：{args.command}")
        _print_compact(result)
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        _print_compact({"kind": "BLOCKED", "reason": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

Update `self_test.py` required files and help assertions:

```python
required = required + (
    "pipeline_policy.json",
    "scripts/pipeline_policy.py",
    "scripts/pipeline_runner.py",
)

runner_help = subprocess.run(
    [sys.executable, str(SKILL_ROOT / "scripts" / "pipeline_runner.py"), "--help"],
    check=True,
    capture_output=True,
    text=True,
    encoding="utf-8",
    env=child_environment,
).stdout
for command in ("status", "approve-start", "next", "accept-content", "accept-image", "image-failed", "run-local", "approve-rerun", "complete-review"):
    assert command in runner_help
```

- [ ] **Step 4: Run CLI and package self-tests**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "runner_cli or runner_help" -v
python skill-package/product-video-pipeline/scripts/self_test.py
```

Expected: selected pytest tests PASS; self-test prints `product-video-pipeline 自检通过（未联网、未产生费用）`.

- [ ] **Step 5: Commit the operational CLI**

```powershell
git add -- skill-package/product-video-pipeline/scripts/pipeline_runner.py skill-package/product-video-pipeline/scripts/self_test.py tests/test_portable_skill_package.py
git commit -m "feat: expose low-cost pipeline runner CLI"
```

---

### Task 7: Rewrite the runtime instructions around the runner

**Files:**
- Modify: `skill-package/product-video-pipeline/SKILL.md`
- Modify: `skill-package/product-video-pipeline/references/workflow.md`
- Modify: `skill-package/product-video-pipeline/references/image-generation-routing.md`
- Modify: `skill-package/product-video-pipeline/references/review-learning.md`
- Modify: `skill-package/product-video-pipeline/references/delivery-contract.md`
- Modify: `skill-package/product-video-pipeline/references/autodl-h3.md`
- Modify: `skill-package/product-video-pipeline/references/install.md`
- Modify: `tests/test_portable_skill_package.py`

**Interfaces:**
- Consumes the Task 6 CLI.
- Produces a compact Agent contract: call `pipeline_runner.py next`, fulfill only the returned external action, then call `next` again.
- Detailed references become human/audit documentation rather than mandatory repeated runtime context.

- [ ] **Step 1: Replace obsolete documentation assertions with failing low-cost contract assertions**

Update the image-routing test and add a token-size guard:

```python
def test_image_generation_routing_is_gpt_web_only_and_review_free():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    routing = (SKILL_ROOT / "references" / "image-generation-routing.md").read_text(encoding="utf-8")
    combined = skill + "\n" + routing
    assert "GPT 网页端是唯一生图渠道" in combined
    assert "不进行人工图片审核" in combined
    assert "不调用模型进行二次视觉审核" in combined
    assert "本机 Codex 界面 → ChatGPT 网页端 → 第三方 API 生图" not in combined
    assert "pipeline_runner.py accept-image" in combined


def test_skill_runtime_entry_is_compact_and_runner_driven():
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "pipeline_runner.py next" in text
    assert "只执行返回的一个外部动作" in text
    assert "不得把完整日志粘贴回模型上下文" in text
    assert len(text) <= 9000
```

- [ ] **Step 2: Run documentation tests and verify failure**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "routing_is_gpt_web_only or runtime_entry_is_compact" -v
```

Expected: FAIL because current instructions require multi-channel routing and repeated reviews.

- [ ] **Step 3: Incrementally update the documentation**

Before each patch run:

```powershell
git diff -- skill-package/product-video-pipeline/SKILL.md skill-package/product-video-pipeline/references/workflow.md skill-package/product-video-pipeline/references/image-generation-routing.md skill-package/product-video-pipeline/references/review-learning.md skill-package/product-video-pipeline/references/delivery-contract.md skill-package/product-video-pipeline/references/autodl-h3.md
```

Preserve unrelated existing changes. Rewrite the runtime section of `SKILL.md` around this exact loop:

```markdown
## Runtime loop

1. 完成启动清单和预算确认后调用 `pipeline_runner.py approve-start`。
2. 调用 `pipeline_runner.py next` 并只执行返回的一个外部动作。
3. `GPT_WEB_IMAGE_REQUIRED` 必须在一次浏览器动作内完成 GPT 网页提交、等待和原图下载，然后调用 `pipeline_runner.py accept-image`。
4. 图片不进行人工审核，也不调用模型进行二次视觉审核；技术检查和自动晋升由脚本完成。
5. `run-local`、轮询、下载、哈希、晋升、审计和恢复不得调用 DeepSeek。
6. 动作完成后再次调用 `next`，直到 `USER_FINAL_REVIEW_REQUIRED`、`USER_RERUN_APPROVAL_REQUIRED`、`BLOCKED` 或 `DONE`。
7. 不得把完整日志粘贴回模型上下文；只读取脚本输出的紧凑 JSON。
```

Remove runtime instructions that require rereading full references at every node. Keep startup, payment, V02, final review, seven-deliverable, and hash safety rules. Update all image references to state that GPT Web is the only provider and visual review is intentionally skipped by user policy.

- [ ] **Step 4: Run all documentation and package integrity tests**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "skill or routing or documented or required_portable_resources" -v
```

Expected: all selected tests PASS with no stale multi-provider route assertion.

- [ ] **Step 5: Commit the runner-driven documentation**

```powershell
git add -- skill-package/product-video-pipeline/SKILL.md skill-package/product-video-pipeline/references/workflow.md skill-package/product-video-pipeline/references/image-generation-routing.md skill-package/product-video-pipeline/references/review-learning.md skill-package/product-video-pipeline/references/delivery-contract.md skill-package/product-video-pipeline/references/autodl-h3.md skill-package/product-video-pipeline/references/install.md tests/test_portable_skill_package.py
git commit -m "docs: route product video execution through low-cost runner"
```

---

### Task 8: Update source version and package self-checks

**Files:**
- Modify: `skill-package/product-video-pipeline/VERSION`
- Modify: `skill-package/product-video-pipeline/scripts/self_test.py`
- Modify: `tests/test_portable_skill_package.py`

**Interfaces:**
- Produces source version `1.7.0`.
- Makes the offline self-test require the compact policy and both new Python modules.

- [ ] **Step 1: Add failing source-version test**

Append:

```python
def test_current_source_is_v1_7_with_low_cost_runtime_files():
    assert (SKILL_ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.7.0"
    for relative in (
        "pipeline_policy.json",
        "scripts/pipeline_policy.py",
        "scripts/pipeline_runner.py",
    ):
        assert (SKILL_ROOT / relative).is_file()
```

- [ ] **Step 2: Verify the release test fails**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py::test_current_source_is_v1_7_with_low_cost_runtime_files -v
```

Expected: FAIL because the source version is still `1.6.1`.

- [ ] **Step 3: Update version and package assertions**

Set `skill-package/product-video-pipeline/VERSION` to:

```text
1.7.0
```

Add these required resources to `self_test.py` and the portable-resource test:

```python
"pipeline_policy.json",
"scripts/pipeline_policy.py",
"scripts/pipeline_runner.py",
```

Update only assertions that represent the current source version from `1.6.1` to `1.7.0`; retain historical archive assertions for v1.5.0, v1.6.0, and v1.6.1.

- [ ] **Step 4: Run source-version and self-tests**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "current_source_is_v1_7 or required_portable_resources or runner" -v
python skill-package/product-video-pipeline/scripts/self_test.py
```

Expected:

- all selected pytest tests PASS;
- self-test reports no network and no charge;

- [ ] **Step 5: Commit the source version**

Run:

```powershell
git add -- skill-package/product-video-pipeline/VERSION skill-package/product-video-pipeline/scripts/self_test.py tests/test_portable_skill_package.py
git commit -m "chore: prepare product video pipeline v1.7.0"
```

Expected: the version and package self-check commit succeeds.

---

### Task 9: Perform a no-charge end-to-end acceptance run

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/pipeline_runner.py`
- Modify: `tests/test_portable_skill_package.py`
- Test artifact: a fresh temporary directory created by pytest; do not use a real product batch.

**Interfaces:**
- Verifies the complete external-action loop without GPT Web, DeepSeek, or AutoDL network calls by supplying fixture images and monkeypatched AutoDL responses.

- [ ] **Step 1: Add the failing end-to-end dry-run test**

Append:

```python
def test_low_cost_pipeline_end_to_end_dry_run(tmp_path, monkeypatch):
    runner = load_script("pipeline_runner.py")
    policy = json.loads((SKILL_ROOT / "pipeline_policy.json").read_text(encoding="utf-8"))
    batch = tmp_path / "20260907_批次001"
    item = batch / "V001_轻便_待生成"
    process = item / "_工作文件" / "生成过程"
    process.mkdir(parents=True)
    for filename in ("分镜提示词.txt", "合理尾帧提示词.txt", "封面提示词.txt"):
        (process / filename).write_text(filename, encoding="utf-8")

    state = runner.load_or_create_state(batch, policy)
    runner.transition(state, "RUNNING_AUTOMATICALLY", reason="test approval")
    runner.save_state(batch, state)

    colors = {"分镜图.png": "blue", "尾帧图.png": "green", "封面图.png": "orange"}
    for artifact, color in colors.items():
        raw = tmp_path / artifact
        Image.new("RGB", (1152, 2048), color).save(raw)
        runner.accept_web_image(item, artifact, raw)

    before_calls = dict(state.model_calls_by_video)
    monkeypatch.setattr(runner, "run_autodl_item", lambda *a, **k: {"ok": True, "dry_run": True, "request_hash": "dry-hash"})
    result = runner.run_local_until_gate(batch, state, policy, dry_run=True)

    assert result["kind"] == "USER_FINAL_REVIEW_REQUIRED"
    assert state.model_calls_by_video == before_calls
    assert (item / "分镜图.png").exists()
    assert (item / "尾帧图.png").exists()
    assert (item / "封面图.png").exists()
```

- [ ] **Step 2: Run the end-to-end test and verify failure**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py::test_low_cost_pipeline_end_to_end_dry_run -v
```

Expected: FAIL if any integration transition is missing, most likely `run_local_until_gate`.

- [ ] **Step 3: Implement the minimal integration loop**

Add to `pipeline_runner.py`:

```python
def run_local_until_gate(
    batch_dir: Path,
    state: RunnerState,
    policy: dict[str, object],
    *,
    dry_run: bool = False,
) -> dict[str, object]:
    for item in _video_items(batch_dir):
        required = ("分镜图.png", "尾帧图.png", "封面图.png")
        if not all((item / name).is_file() for name in required):
            return next_action(batch_dir, state, policy)
        result = run_autodl_item(batch_dir, item, state, dry_run=dry_run)
        if not result.get("ok"):
            transition(state, "BLOCKED", reason=str(result.get("status", "视频执行失败")))
            save_state(batch_dir, state)
            return {"kind": "BLOCKED", "reason": state.blocked_reason}
    transition(state, "WAITING_FINAL_REVIEW", reason="全部视频候选准备完成")
    save_state(batch_dir, state)
    return {"kind": "USER_FINAL_REVIEW_REQUIRED"}
```

- [ ] **Step 4: Run the end-to-end test and full suite**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py::test_low_cost_pipeline_end_to_end_dry_run -v
python -m pytest tests/test_portable_skill_package.py -v
python skill-package/product-video-pipeline/scripts/self_test.py
```

Expected: all tests PASS; no network call and no paid submission occurs.

- [ ] **Step 5: Commit the acceptance path**

```powershell
git add -- skill-package/product-video-pipeline/scripts/pipeline_runner.py tests/test_portable_skill_package.py
git commit -m "test: verify low-cost pipeline dry-run end to end"
```

---

### Task 10: Package and verify the portable v1.7.0 release

**Files:**
- Modify: `tests/test_portable_skill_package.py`
- Create: `release/product-video-pipeline-v1.7.0.zip`

**Interfaces:**
- Consumes the tested v1.7.0 source from Tasks 1–9.
- Produces portable archive `release/product-video-pipeline-v1.7.0.zip`.
- Package includes the compact policy and runner, and excludes `.env`, credentials, `__pycache__`, `.pyc`, task outputs, and local state.

- [ ] **Step 1: Add the failing release-package test**

Append:

```python
def test_v1_7_release_contains_low_cost_runner_and_no_secrets():
    archive = REPO_ROOT / "release" / "product-video-pipeline-v1.7.0.zip"
    assert archive.is_file()
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        required = {
            "product-video-pipeline/VERSION",
            "product-video-pipeline/pipeline_policy.json",
            "product-video-pipeline/scripts/pipeline_policy.py",
            "product-video-pipeline/scripts/pipeline_runner.py",
        }
        assert required <= names
        assert bundle.read("product-video-pipeline/VERSION").decode("utf-8").strip() == "1.7.0"
        assert not any(
            name.endswith(".env")
            or name.endswith(".pyc")
            or "__pycache__" in name
            or "流水线状态.json" in name
            for name in names
        )
```

- [ ] **Step 2: Verify the release test fails**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py::test_v1_7_release_contains_low_cost_runner_and_no_secrets -v
```

Expected: FAIL because the v1.7.0 archive does not exist.

- [ ] **Step 3: Build the deterministic zip**

Run from the repository root:

```powershell
$sourceRoot = (Resolve-Path 'skill-package\product-video-pipeline').Path
$releasePath = Join-Path (Resolve-Path 'release').Path 'product-video-pipeline-v1.7.0.zip'
$stagingRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('product-video-pipeline-v1.7.0-' + [guid]::NewGuid().ToString('N'))
$stagingSkill = Join-Path $stagingRoot 'product-video-pipeline'
New-Item -ItemType Directory -Path $stagingSkill -Force | Out-Null
Get-ChildItem -LiteralPath $sourceRoot -Recurse -File | Where-Object {
    $_.Name -ne '.env' -and
    $_.Extension -ne '.pyc' -and
    $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and
    $_.Name -ne '流水线状态.json'
} | ForEach-Object {
    $relative = $_.FullName.Substring($sourceRoot.Length).TrimStart('\')
    $target = Join-Path $stagingSkill $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $target
}
Compress-Archive -LiteralPath $stagingSkill -DestinationPath $releasePath -Force
Remove-Item -LiteralPath $stagingRoot -Recurse -Force
```

- [ ] **Step 4: Run release and full offline verification**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py::test_v1_7_release_contains_low_cost_runner_and_no_secrets -v
python -m pytest tests/test_portable_skill_package.py -v
python skill-package/product-video-pipeline/scripts/self_test.py
python skill-package/product-video-pipeline/scripts/pipeline_runner.py --help
git diff --check
```

Expected:

- release test and full pytest suite PASS;
- self-test reports no network and no charge;
- runner help lists all nine supported commands;
- `git diff --check` prints no errors.

- [ ] **Step 5: Inspect archive contents and commit the release**

Run:

```powershell
python -c "import zipfile; p='release/product-video-pipeline-v1.7.0.zip'; z=zipfile.ZipFile(p); print('\n'.join(z.namelist())); assert not any(n.endswith('.env') or n.endswith('.pyc') or '__pycache__' in n for n in z.namelist())"
git add -- tests/test_portable_skill_package.py release/product-video-pipeline-v1.7.0.zip
git commit -m "release: package product video pipeline v1.7.0"
```

Expected: archive listing includes the policy and runner files, contains no secret/cache files, and the release commit succeeds.

---

## Final verification checklist

- [ ] Run `git status --short` and confirm pre-existing unrelated files remain untouched.
- [ ] Run `git diff --check`.
- [ ] Run `python -m pytest tests/test_portable_skill_package.py -v`.
- [ ] Run `python skill-package/product-video-pipeline/scripts/self_test.py`.
- [ ] Inspect `release/product-video-pipeline-v1.7.0.zip` for secrets and caches.
- [ ] Run one fixture-only dry-run and verify model-call counters do not change during image normalization, AutoDL dry-run, polling simulation, download simulation, promotion, and audit.
- [ ] Do not run GPT Web generation or a paid AutoDL submission as part of verification unless the user separately authorizes those external actions.
