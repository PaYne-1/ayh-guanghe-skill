# Native 4K Unattended Product Video Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make auto-mode product videos use reference-locked native 4K images, a single-shot/full-body/closed-dialogue MiniMax prompt, one startup total budget, unattended V01 execution, and delivery of verified real absolute file paths.

**Architecture:** Add a focused `generation_prompt_contract.py` module that owns deterministic prompt compilation and preflight validation. Keep `pipeline_runner.py` responsible for durable actions, budgets, provider recovery, and mode-specific state transitions. Auto mode consumes the initial configuration as V01 authorization and ends at `WAITING_USER_FEEDBACK`; learning mode preserves its existing approval and final-review flow.

**Tech Stack:** Python 3 standard library, Pillow image validation, existing ffprobe/ffmpeg technical checks, pytest, JSON/Markdown skill contracts.

## Global Constraints

- This implementation changes source, rules, and offline tests only; do not change `VERSION` and do not create, rebuild, edit, or deliver a release ZIP.
- Unattended execution applies only to `run_mode == "auto"`; `learning` keeps its existing approval and final-video review behavior.
- The initial auto-mode response is configuration approval, V01 payment authorization, and continuous execution authorization; there is no second “confirm execution” step.
- The user supplies one `max_budget_yuan`; internal image and AutoDL ledgers remain separate, and all V01 video cost is reserved before third-party image spending is allowed.
- V02 is never authorized by the initial budget and is never submitted automatically; it still requires user feedback followed by explicit per-video cost approval.
- Product reference images are the sole product-appearance source for storyboard, tail, cover, and video; generated prompts must not describe specific product appearance.
- All generated images must be native `2160×3840`, 9:16, with both sides divisible by 16 and exactly 8,294,400 pixels; lower-resolution images must be rejected, never upscaled into compliance.
- MiniMax-H3 native audio remains enabled; specified Chinese lines occur exactly once, speakers alternate without overlap, the non-speaker is silent with mouth closed, and no extra/unknown-language voice or BGM is allowed.
- Auto mode performs deterministic file/media checks but no image content review, video semantic review, visual-model review, or speech transcription.
- Every delivered video path must be absolute, exist outside temporary directories, be the titled root-level MP4, and match the candidate/technical-evidence SHA-256.
- All tests are offline and must not invoke GPT Web, a third-party API, DeepSeek, or AutoDL.

## File Map

- Create `skill-package/product-video-pipeline/scripts/generation_prompt_contract.py`: prompt constants, compilation, forbidden-appearance checks, and deterministic image/video preflight.
- Create `tests/test_generation_prompt_contract.py`: direct unit tests for reference locking, 4K request text, shot framing, exact dialogue, and missing-rule failures.
- Create `tests/test_unattended_auto_mode.py`: offline state-machine tests for one-step authorization, combined budget, automatic delivery, real paths, and V02 gating.
- Modify `skill-package/product-video-pipeline/scripts/pipeline_runner.py`: integrate compiled prompts, strict native-4K acceptance, total-budget allocation, auto activation, mode routing, V01 promotion, delivery manifest, and feedback state.
- Modify `skill-package/product-video-pipeline/scripts/pipeline_policy.py` and `pipeline_policy.json`: five-field API connection config, mode-aware final behavior, and `WAITING_USER_FEEDBACK`.
- Modify `skill-package/product-video-pipeline/scripts/workflow_cli.py`: persist first-response auto authorization and align content validation with provider-neutral product prompts.
- Modify existing runtime/package tests and `self_test.py`: update fixtures while preserving learning-mode regression coverage.
- Modify `SKILL.md` and the relevant references: document native 4K, product-reference-only prompts, unattended auto mode, one total budget, closed dialogue, V02 gating, and absolute-path delivery.

---

### Task 1: Centralize image and video generation prompt contracts

**Files:**
- Create: `skill-package/product-video-pipeline/scripts/generation_prompt_contract.py`
- Create: `tests/test_generation_prompt_contract.py`

**Interfaces:**
- Produces: `compile_image_prompt(base_prompt: str, artifact_name: str) -> str`.
- Produces: `validate_image_request(prompt: str, reference_paths: list[str], width: int, height: int) -> list[str]`.
- Produces: `compile_video_prompt(base_prompt: str, people: list[dict[str, object]], segments: list[dict[str, object]]) -> str`.
- Produces: `validate_video_request(prompt: str, segments: list[dict[str, object]]) -> list[str]`.
- Produces: `FORBIDDEN_PRODUCT_APPEARANCE_TERMS`, containing component-description nouns that must never be inferred in prompts, while generic “the whole referenced product remains visible” composition language stays allowed.

- [ ] **Step 1: Write failing image-contract tests**

Create tests that import the new module by file path and assert the wished-for API:

```python
def test_image_prompt_uses_reference_as_only_product_source():
    prompt = contract.compile_image_prompt("老人和家属在公园出行", "分镜图.png")
    assert "产品参考图是唯一产品依据" in prompt
    assert "禁止重新设计、补画、删减、替换或推测" in prompt
    assert "2160×3840" in prompt
    assert "8,294,400" in prompt


@pytest.mark.parametrize(
    "appearance",
    ["黑色脚踏板", "红色车架", "加粗轮胎", "圆形控制器"],
)
def test_specific_product_appearance_is_rejected(appearance):
    with pytest.raises(ValueError, match="产品外观"):
        contract.compile_image_prompt(f"老人坐在带有{appearance}的产品上", "分镜图.png")
```

Also assert that “产品整体始终完整位于画面安全区” is allowed and that all three artifact names are accepted while unknown artifacts fail.

- [ ] **Step 2: Write failing video-contract tests**

Use two people and three fixed segments. Assert the compiled prompt contains exact `0–15秒`, `一个连续镜头`, `固定中远景`, the full-body/product-safe-area rule, strict alternation, closed-mouth silence, zero extra voice, native Chinese dialogue only, and no BGM. Count every exact dialogue string in the compiled result:

```python
for segment in segments:
    assert prompt.count(segment["dialogue"]) == 1
assert contract.validate_video_request(prompt, segments) == []
```

Mutate one required block or duplicate a dialogue and assert a stable error code such as `video.dialogue_exactly_once` or `video.closed_dialogue_missing`.

- [ ] **Step 3: Run tests and capture RED**

Run:

```powershell
python -m pytest tests/test_generation_prompt_contract.py -q
```

Expected: collection/import failure because `generation_prompt_contract.py` does not exist.

- [ ] **Step 4: Implement the focused prompt module**

Use named, delimited prompt blocks rather than scattered keyword concatenation:

```python
IMAGE_SIZE = (2160, 3840)
IMAGE_ARTIFACTS = {"分镜图.png", "尾帧图.png", "封面图.png"}
FORBIDDEN_PRODUCT_APPEARANCE_TERMS = (
    "踏板", "脚踏", "车架", "轮胎", "控制器", "扶手", "靠背",
)

PRODUCT_REFERENCE_BLOCK = """【产品参考锁定】
上传的产品参考图是唯一产品依据。直接使用参考图中的产品，保持结构、部件、比例、连接关系和相对位置完全不变。
禁止重新设计、补画、删减、替换或推测任何产品部件。不要用文字重新描述产品的颜色、形状、材质或部件外观。"""

NATIVE_4K_BLOCK = """【原生输出参数】
直接生成原生2160×3840竖屏图，9:16；最大边3840px；宽高均为16px整数倍；总像素8,294,400。禁止先生成小图再放大。"""
```

`compile_image_prompt` strips input, rejects forbidden phrases, and returns base scene text followed by exactly one copy of both blocks. `compile_video_prompt` rejects appearance phrases, verifies two distinct people and non-overlapping ordered segments, then emits exactly one line per segment plus fixed visual/audio blocks. Validators return stable machine-readable error codes and never edit prompts.

- [ ] **Step 5: Run unit tests and compile check**

Run:

```powershell
python -m pytest tests/test_generation_prompt_contract.py -q
python -m py_compile skill-package/product-video-pipeline/scripts/generation_prompt_contract.py
```

Expected: all prompt-contract tests pass and compile exits 0.

- [ ] **Step 6: Commit**

```powershell
git add skill-package/product-video-pipeline/scripts/generation_prompt_contract.py tests/test_generation_prompt_contract.py
git commit -m "feat: add locked generation prompt contracts"
```

---

### Task 2: Issue native-4K image actions and reject non-native results

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/pipeline_runner.py:780-875,1245-1300`
- Modify: `tests/test_image_provider_selection.py`
- Modify: `tests/test_portable_skill_package.py`
- Modify: `tests/test_pipeline_runtime_contract.py`

**Interfaces:**
- Consumes: `compile_image_prompt` and `validate_image_request` from Task 1.
- Produces: `_load_prompt_contract()` sibling-module loader in `pipeline_runner.py`.
- Produces: image actions with `width: 2160`, `height: 3840`, `size: "2160x3840"`, `native_resolution_required: True`, and `prompt_path` pointing to a compiled submission prompt.
- Produces: `validate_native_4k_image(source: Path, output: Path, *, width: int = 2160, height: int = 3840) -> dict[str, object]` that copies/converts without resampling.

- [ ] **Step 1: Add failing provider-action and acceptance tests**

Parameterize GPT Web and third-party API. Assert the action has exact dimensions, reads a compiled prompt containing both lock blocks, includes real reference paths, and adds for API actions:

```python
assert action["request_parameters"] == {"width": 2160, "height": 3840}
```

Add image acceptance cases for `(2160, 3840)` passing and `(1080, 1920)`, `(1152, 2048)`, and `(3840, 2160)` failing. After failure assert neither the candidate nor root artifact is promoted and no resized 4K file exists.

Update every existing generated-image acceptance helper in `tests/test_image_provider_selection.py`, `tests/test_pipeline_runtime_contract.py`, and `tests/test_portable_skill_package.py` to save a solid-color `2160×3840` PNG. Keep product inputs and style-reference fixtures at their small sizes because source references are not generated deliverables. Preserve explicit low-resolution fixtures only in tests that assert strict rejection.

- [ ] **Step 2: Run focused tests and capture RED**

Run:

```powershell
python -m pytest tests/test_image_provider_selection.py -k "native_4k or exact_image_dimensions" -q
```

Expected: actions lack exact parameters and current acceptance upscales smaller 9:16 files.

- [ ] **Step 3: Compile image prompts before reserving actions**

For each artifact, read the base prompt, call `compile_image_prompt`, validate it with the resolved reference paths and exact dimensions, and atomically write it to:

```python
compiled_name = {
    "分镜图.png": "分镜提交提示词.txt",
    "尾帧图.png": "尾帧提交提示词.txt",
    "封面图.png": "封面提交提示词.txt",
}[artifact]
```

If validation returns errors, record `item_failures[video_id] = {"kind": "content", "reason": "图片提交提示词预检失败：" + ",".join(issues)}` and do not call `_reserve_action` or `_reserve_image_api_action`. Both providers receive the same compiled prompt path and dimension fields.

- [ ] **Step 4: Replace resize normalization with strict native validation**

Implement:

```python
if image.size != (width, height):
    raise ValueError(f"生成图片必须为原生{width}×{height}，禁止本地放大")
normalized = image.convert("RGB")
normalized.save(temporary, format="PNG")
```

Remove the `Image.Image.resize` call. Evidence must report identical `source_size` and `target_size`; conversion to RGB is allowed, spatial resampling is not. Update `accept_generated_image` to call `validate_native_4k_image` and return the actual provider from the reserved action call site rather than a hardcoded provider.

- [ ] **Step 5: Run image/provider regression tests**

Run:

```powershell
python -m pytest tests/test_generation_prompt_contract.py tests/test_image_provider_selection.py tests/test_portable_skill_package.py -q -k "image or prompt or provider"
```

Expected: both providers issue native-4K actions, only exact native images promote, and existing channel/ledger behavior remains green.

- [ ] **Step 6: Commit**

```powershell
git add skill-package/product-video-pipeline/scripts/pipeline_runner.py tests/test_image_provider_selection.py tests/test_portable_skill_package.py tests/test_pipeline_runtime_contract.py
git commit -m "feat: require native 4k image results"
```

---

### Task 3: Compile and preflight the single-shot closed-dialogue video payload

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/pipeline_runner.py:1126-1155`
- Modify: `skill-package/product-video-pipeline/scripts/workflow_cli.py:1335-1425`
- Modify: `tests/test_generation_prompt_contract.py`
- Modify: `tests/test_pipeline_runtime_contract.py`

**Interfaces:**
- Consumes: `compile_video_prompt` and `validate_video_request` from Task 1.
- Produces: `prepare_payload(batch: Path, item: Path, state: RunnerState) -> Path` whose `payload["prompt"]` is the compiled and validated final prompt, not raw model prose plus a loose dialogue appendix.
- Produces: `validate_content_package` errors `product.appearance_description_forbidden` for forbidden source descriptions; final submission preflight remains the authoritative paid-action gate.

- [ ] **Step 1: Add failing final-payload tests**

Create a valid item with exact 4K first/last frames and assert the persisted `提交请求.json.prompt` contains every required visual/audio block. Assert each dialogue appears once, with its `speaker_id`, start, and end. Add mutations for duplicate dialogue, missing silent non-speaker rule, extra voice permission, and a specific product appearance description; each must fail before `_reserve_payment` and leave both video and image ledgers unchanged.

- [ ] **Step 2: Run tests and capture RED**

Run:

```powershell
python -m pytest tests/test_generation_prompt_contract.py tests/test_pipeline_runtime_contract.py -k "closed_dialogue or final_video_prompt_preflight" -q
```

Expected: current `prepare_payload` lacks the closed-dialogue/full-body blocks and accepts forbidden product appearance prose.

- [ ] **Step 3: Integrate the compiled video prompt**

Replace manual `parts` concatenation in `prepare_payload` with:

```python
prompt_contract = _load_prompt_contract()
compiled = prompt_contract.compile_video_prompt(
    str(package["video_prompt"]),
    list(package["people"]),
    list(package["script_segments"]),
)
issues = prompt_contract.validate_video_request(compiled, list(package["script_segments"]))
if issues:
    raise ValueError("视频提交提示词预检失败：" + ",".join(issues))
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
```

Write the compiled prompt to `_工作文件/生成过程/视频提交提示词.txt` before persisting the JSON payload. Keep payload binding and deterministic seed behavior unchanged.

- [ ] **Step 4: Align early content validation without duplicating compilation**

Import only the forbidden-appearance checker into `workflow_cli.py`. Add an early error if any of `storyboard_prompt`, `last_frame_prompt`, or `video_prompt` contains a forbidden phrase. Do not require the compiled blocks in model-produced content; Task 1's compiler adds those once at the external-action boundary.

- [ ] **Step 5: Run focused and runtime tests**

Run:

```powershell
python -m pytest tests/test_generation_prompt_contract.py tests/test_pipeline_runtime_contract.py tests/test_portable_skill_package.py -q -k "content or prompt or payload or dialogue"
```

Expected: all selected tests pass; malformed prompts are stopped before paid reservation, while valid payload bindings remain deterministic.

- [ ] **Step 6: Commit**

```powershell
git add skill-package/product-video-pipeline/scripts/pipeline_runner.py skill-package/product-video-pipeline/scripts/workflow_cli.py tests/test_generation_prompt_contract.py tests/test_pipeline_runtime_contract.py tests/test_portable_skill_package.py
git commit -m "feat: enforce closed dialogue video preflight"
```

---

### Task 4: Replace separate startup approvals with one auto-mode total budget

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/pipeline_policy.py`
- Modify: `skill-package/product-video-pipeline/pipeline_policy.json`
- Modify: `skill-package/product-video-pipeline/scripts/workflow_cli.py:1185-1320`
- Modify: `skill-package/product-video-pipeline/scripts/pipeline_runner.py:410-610,1210-1250,1830-1955`
- Create: `tests/test_unattended_auto_mode.py`
- Modify: `tests/test_image_provider_selection.py`

**Interfaces:**
- Produces: third-party connection config with five required user fields: `api_name`, `base_url`, `model`, `api_key_env`, `unit_price_yuan`; `batch_budget_yuan` is no longer user input.
- Produces: `_auto_budget_manifest(confirmation: dict[str, object], video_prices: dict[str, str]) -> dict[str, str]` with `total_budget_yuan`, `reserved_v01_video_yuan`, `initial_image_estimate_yuan`, and `image_budget_yuan`.
- Produces: `_activate_auto_batch(batch: Path, state: RunnerState, policy: dict[str, object]) -> None`.
- Preserves: `approve-start` as the explicit learning-mode approval command.

- [ ] **Step 1: Add failing one-budget auto activation tests**

Create one-video auto fixtures for both providers. The initialization confirmation must contain `startup_authorization: "initial_user_reply"` and one `max_budget_yuan`. After populating a real offline `prices_by_video`, call `next` directly—never `approve-start`—and assert it returns `BATCH_CONTENT_REQUIRED` and seals the manifest.

For third-party API with unit price `0.20`, video price `3.00`, one video, and total budget `5.00`, assert:

```python
assert manifest["reserved_v01_video_yuan"] == "3.00"
assert manifest["initial_image_estimate_yuan"] == "0.60"
assert manifest["image_budget_yuan"] == "2.00"
```

With total budget `3.50`, assert auto activation blocks before content/image/video action because the initial three images plus V01 exceed the total.

- [ ] **Step 2: Add failing budget isolation tests**

Prove image reservations cannot exceed `image_budget_yuan`, V01 video reservations cannot exceed `reserved_v01_video_yuan`, and combined reserved/spent costs cannot exceed `total_budget_yuan`. Assert GPT Web initial image estimate is `0` and no image ledger entry is created.

- [ ] **Step 3: Run tests and capture RED**

Run:

```powershell
python -m pytest tests/test_unattended_auto_mode.py -k "activation or total_budget" -q
```

Expected: `next` returns `USER_START_APPROVAL_REQUIRED`, API config still demands a separate batch budget, and no combined allocation exists.

- [ ] **Step 4: Change API config and policy to one total budget**

Set `IMAGE_API_FIELDS` to the five connection/price fields. `normalize_image_api_config` returns only those five fields; accept and discard a legacy `batch_budget_yuan` key when loading old configuration, but never write it into new confirmations.

Change policy approvals to:

```json
"approvals": {
  "auto_initial_response_authorizes_v01": true,
  "learning_startup_budget": true,
  "v02": "user_required",
  "final_video": {"auto": "deliver_without_review", "learning": "user_required"}
}
```

Add `WAITING_USER_FEEDBACK` to policy states and the runner's `VALID_STATES`.

- [ ] **Step 5: Persist initial auto authorization**

In `initialize_batch`, write:

```python
"startup_authorization": (
    "initial_user_reply" if run_mode == "auto" else "learning_review_required"
),
"max_budget_yuan": str(Decimal(max_budget_yuan)),
```

Update startup summary copy to say auto mode is authorized by the initial reply. Continue storing only the API-key environment variable name.

- [ ] **Step 6: Implement auto activation and manifest allocation**

Include `run_mode` and the four budget fields in `_confirmation_manifest`. For API images, calculate three initial images per video; `image_budget_yuan = total_budget_yuan - reserved_v01_video_yuan`. Require `reserved_v01_video_yuan + initial_image_estimate_yuan <= total_budget_yuan`.

Normalize a missing `run_mode` in pre-existing hand-built confirmations to `learning` so historical runner states retain their explicit review path. Only the literal sealed value `auto` enables unattended activation or delivery.

When `next_action` sees `WAITING_START_APPROVAL`:

```python
if confirmation.get("run_mode") == "auto":
    _activate_auto_batch(batch_dir, state, policy)
    return next_action(batch_dir, state, policy)
return {"kind": "USER_START_APPROVAL_REQUIRED"}
```

Activation requires complete per-video prices, the named API credential when applicable, and `startup_authorization == "initial_user_reply"`. Missing local configuration returns a non-paid `LOCAL_AUTO_CONFIGURATION_REQUIRED`; budget insufficiency returns `BLOCKED`. It must never synthesize a provider or price.

Keep `approve-start` available only for learning mode. Set `state.approved_budget` to total budget and `state.estimated_v01_total` to reserved V01 video cost. Change `_reserve_image_api_action` to use sealed `image_budget_yuan`, and `_reserve_payment` to cap V01 ledger rows at `reserved_v01_video_yuan`; V02 continues using separate explicit authorization.

- [ ] **Step 7: Run auto and existing approval tests**

Run:

```powershell
python -m pytest tests/test_unattended_auto_mode.py tests/test_image_provider_selection.py tests/test_pipeline_runtime_contract.py -q -k "budget or approval or provider or activation"
```

Expected: auto mode starts from its initial reply with one total budget; learning mode still waits for and validates explicit `approve-start`; V02 remains separately gated.

- [ ] **Step 8: Commit**

```powershell
git add skill-package/product-video-pipeline/pipeline_policy.json skill-package/product-video-pipeline/scripts/pipeline_policy.py skill-package/product-video-pipeline/scripts/workflow_cli.py skill-package/product-video-pipeline/scripts/pipeline_runner.py tests/test_unattended_auto_mode.py tests/test_image_provider_selection.py tests/test_pipeline_runtime_contract.py
git commit -m "feat: authorize auto v01 with one total budget"
```

---

### Task 5: Auto-promote V01 and deliver verified absolute paths

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/pipeline_runner.py:1170-1220,1425-1540,1584-1815,2040-2140`
- Modify: `tests/test_unattended_auto_mode.py`
- Modify: `tests/test_pipeline_mixed_batch.py`
- Modify: `tests/test_pipeline_runtime_contract.py`

**Interfaces:**
- Produces: `_promote_auto_video(item: Path, technical: dict[str, object], workflow: object) -> Path`.
- Produces: `_delivery_row(item: Path, state: RunnerState) -> dict[str, object]`.
- Produces: `_deliver_auto_batch(batch: Path, state: RunnerState) -> dict[str, object]` returning kind `V01_DELIVERED`, status `WAITING_USER_FEEDBACK`, and `items` as a list of `_delivery_row` mappings.
- Produces: CLI `request-rerun --batch PATH --video-id ID --reason TEXT`, which records feedback but does not authorize payment.

- [ ] **Step 1: Add failing no-review auto delivery test**

Drive an auto fixture through content acceptance, three native-4K image acceptances, offline AutoDL execution, and `run-local`. Assert the result is `V01_DELIVERED`, never `USER_FINAL_REVIEW_REQUIRED`, and state is `WAITING_USER_FEEDBACK`.

For each returned row assert:

```python
video_path = Path(row["video_path"])
item_path = Path(row["item_dir"])
assert video_path.is_absolute() and video_path.is_file()
assert item_path.is_absolute() and item_path.is_dir()
assert video_path.parent == item_path
assert video_path.name == workflow.deliverable_root_path(item_path, "视频.mp4").name
assert runner._sha256(video_path) == row["sha256"] == row["technical"]["sha256"]
assert row["status"] == "V01 已下载，等待用户反馈"
```

Also assert `video_cost_yuan` and provider-appropriate `image_cost_yuan` are present.

- [ ] **Step 2: Add learning-mode and V02 gate regressions**

Drive an equivalent learning fixture and assert it still returns `USER_FINAL_REVIEW_REQUIRED`. For auto delivery, assert `approve-rerun` is rejected before `request-rerun`; after `request-rerun`, state is `WAITING_RERUN_APPROVAL`, but no ledger/action changes until explicit `approve-rerun`. Reject `request-rerun` after V02 to prevent V03.

- [ ] **Step 3: Run tests and capture RED**

Run:

```powershell
python -m pytest tests/test_unattended_auto_mode.py -k "delivery or feedback or learning" -q
```

Expected: auto currently opens `USER_FINAL_REVIEW_REQUIRED`, no delivery rows exist, and `request-rerun` is unknown.

- [ ] **Step 4: Auto-promote technically valid V01 outputs**

Extract the existing title/body/tag auto-promotion loop into `_promote_auto_text_outputs`. Implement `_promote_auto_video` by requiring current technical evidence with `ok is True`, `full_decode is True`, matching version/task ID/candidate/SHA-256, then calling `_promote_passed_candidate` with:

```python
confirmed_by="initial-auto-v01-authorization"
feedback="V01 已完成确定性技术检查；按首次自动模式授权晋升并等待用户反馈"
```

This event records technical delivery, not semantic quality approval.

- [ ] **Step 5: Build and validate delivery rows**

`_delivery_row` must resolve and verify the promoted titled MP4, reject paths under `tempfile.gettempdir()`, verify parent equals the item root, compare current bytes with technical evidence, and return:

```python
{
    "video_id": video_id,
    "publish_title": publish_title,
    "video_path": str(video.resolve()),
    "item_dir": str(item.resolve()),
    "technical": {"ok": True, "duration": duration, "width": width, "height": height, "has_audio": True, "sha256": digest},
    "video_cost_yuan": video_cost,
    "image_cost_yuan": image_cost,
    "sha256": digest,
    "status": "V01 已下载，等待用户反馈",
}
```

Persist the same rows to `批次V01交付.json` so repeated `next` returns a stable, revalidated result rather than relying on chat history.

- [ ] **Step 6: Route auto and learning modes separately**

After all runnable items finish in `run_local_until_gate`, inspect sealed `run_mode`. Auto calls `_deliver_auto_batch`; learning calls `_open_final_review`. `next_action` in `WAITING_USER_FEEDBACK` reloads and revalidates `批次V01交付.json` and returns `V01_DELIVERED`. Do not route this state through `_finalize_outputs` or require item status `COMPLETED`.

- [ ] **Step 7: Add feedback-to-rerun command without payment**

`request-rerun` requires `WAITING_USER_FEEDBACK`, a V01 submission/evidence row, `retry_count == 0`, and a non-empty reason. It records the feedback in the item, creates `USER_RERUN_APPROVAL_REQUIRED` for that video, and transitions to `WAITING_RERUN_APPROVAL`. It must not archive V01, increment retry count, create a payload, or alter any budget ledger; those mutations remain inside existing `approve-rerun` after explicit cost authorization.

- [ ] **Step 8: Run auto/learning/mixed-batch tests**

Run:

```powershell
python -m pytest tests/test_unattended_auto_mode.py tests/test_pipeline_mixed_batch.py tests/test_pipeline_runtime_contract.py -q -k "delivery or final_review or rerun or feedback or mixed"
```

Expected: unattended auto delivery returns real absolute paths, learning review is unchanged, and no automatic V02 path exists.

- [ ] **Step 9: Commit**

```powershell
git add skill-package/product-video-pipeline/scripts/pipeline_runner.py tests/test_unattended_auto_mode.py tests/test_pipeline_mixed_batch.py tests/test_pipeline_runtime_contract.py
git commit -m "feat: deliver auto v01 without review gate"
```

---

### Task 6: Align skill instructions and run source-only acceptance

**Files:**
- Modify: `skill-package/product-video-pipeline/SKILL.md`
- Modify: `skill-package/product-video-pipeline/references/startup-checklist.md`
- Modify: `skill-package/product-video-pipeline/references/content-contract.md`
- Modify: `skill-package/product-video-pipeline/references/image-generation-routing.md`
- Modify: `skill-package/product-video-pipeline/references/workflow.md`
- Modify: `skill-package/product-video-pipeline/references/autodl-h3.md`
- Modify: `skill-package/product-video-pipeline/references/review-learning.md`
- Modify: `skill-package/product-video-pipeline/references/delivery-contract.md`
- Modify: `skill-package/product-video-pipeline/references/ayh-wheelchair-rules.md`
- Modify: `skill-package/product-video-pipeline/scripts/self_test.py`
- Modify: `tests/test_portable_skill_package.py`

**Interfaces:**
- Consumes: runtime behavior from Tasks 1-5.
- Produces: operator instructions matching one-input auto authorization, one total budget, native 4K, provider-neutral product reference locking, closed MiniMax dialogue, `WAITING_USER_FEEDBACK`, and real absolute-path delivery.
- Explicitly does not produce a new `VERSION` or release artifact.

- [ ] **Step 1: Add failing documentation contracts**

Assert the operator docs contain the exact concepts `产品参考图是唯一产品依据`, `禁止用文字重新描述产品外观`, `原生2160×3840`, `禁止本地放大`, `固定中远景`, `非当前说话者嘴巴闭合且完全不发声`, `清单之外零人声`, `本批次最高总预算`, `首次回复同时授权 V01`, `WAITING_USER_FEEDBACK`, and `真实存在的绝对路径`.

Assert global instructions no longer require a second auto start approval, separate user-entered image budget, auto-mode image/final-video review, or product-component descriptions such as the old black continuous footplate prompt rule. Keep those historical product facts only as diagnostic/manual-reference knowledge clearly marked “不得注入生成提示词”.

- [ ] **Step 2: Run docs tests and capture RED**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "native_4k or unattended or closed_dialogue or absolute_delivery" -q
```

Expected: new documentation assertions fail against the current review-gated and appearance-descriptive rules.

- [ ] **Step 3: Update the startup and execution contract**

Make the auto-mode first three-block response the only configuration/authorization interaction. Show one total budget. Keep third-party API name/base URL/model/key-env/unit-price fields, but remove a user-entered image batch budget. State that price/budget validation happens locally after the reply and only a hard block returns to the user.

Document the exact autonomous path through `V01_DELIVERED` and `WAITING_USER_FEEDBACK`. State that V01 semantic defects are not automatically judged and V02 always waits for later feedback plus explicit approval.

- [ ] **Step 4: Replace appearance prose with reference-lock instructions**

In content, image routing, workflow, delivery, and wheelchair rules, remove generation instructions that describe footplate color/shape, frame, wheel, controller, or other component appearance. Retain product facts only in a diagnostic subsection headed `人工反馈定位知识（不得注入生成提示词）`. All four generated-prompt contexts must point to the product image as the sole appearance source.

- [ ] **Step 5: Document the visual/audio hard template and native dimensions**

Add the precise dimension constraints and strict no-upscale behavior. Add full `0–15` single-shot, fixed-medium-wide, complete-person/product safe-area rules. Add the exact closed-dialogue semantics, clarifying that correct scripted content does not permit repetition or invented voices.

- [ ] **Step 6: Update offline self-test**

Change its image fixtures to true `2160×3840` PNGs. Add one auto-mode fixture that reaches `V01_DELIVERED` using an offline runner stub and verifies every returned path/hash. Retain a learning fixture that reaches `USER_FINAL_REVIEW_REQUIRED`. Assert no test invokes an external provider.

- [ ] **Step 7: Run complete source verification**

Run:

```powershell
python -m pytest -q -k "not release_source_parity_and_security"
python skill-package/product-video-pipeline/scripts/self_test.py
python -m py_compile skill-package/product-video-pipeline/scripts/generation_prompt_contract.py skill-package/product-video-pipeline/scripts/pipeline_policy.py skill-package/product-video-pipeline/scripts/pipeline_runner.py skill-package/product-video-pipeline/scripts/workflow_cli.py
git diff --check
git diff --name-only 5168fb5..HEAD -- skill-package/product-video-pipeline/VERSION release
```

Expected: all source tests pass; self-test exits 0; compilation succeeds; diff check is silent; the final command prints nothing, proving version and release artifacts were not changed.

- [ ] **Step 8: Commit source documentation and self-test**

```powershell
git add skill-package/product-video-pipeline/SKILL.md skill-package/product-video-pipeline/references skill-package/product-video-pipeline/scripts/self_test.py tests/test_portable_skill_package.py
git commit -m "docs: define unattended native 4k video workflow"
```

## Plan Self-Review

- Spec coverage: product-reference-only prompts, appearance-description prohibition, exact native 4K, strict no-upscale acceptance, single-shot full-body framing, closed MiniMax dialogue, deterministic preflight, one auto input/authorization, unified total budget, separate internal ledgers, automatic V01 execution, no automatic V02, waiting-for-feedback state, real absolute paths, learning-mode preservation, and no release packaging are mapped to Tasks 1-6.
- Placeholder scan: no deferred markers or unspecified implementation steps remain; every production change has an exact interface, test, command, and expected result.
- Type consistency: `compile_image_prompt`, `validate_image_request`, `compile_video_prompt`, `validate_video_request`, `_auto_budget_manifest`, `_activate_auto_batch`, `_promote_auto_video`, `_delivery_row`, `_deliver_auto_batch`, `WAITING_USER_FEEDBACK`, `V01_DELIVERED`, and `request-rerun` retain the same names and semantics across tasks.
- Scope: prompt construction is isolated in one new module; the existing runner keeps state, cost, recovery, and delivery; no release/version work is included.
