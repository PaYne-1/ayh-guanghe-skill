# Startup Image Provider Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require every product-video batch to choose either GPT Web or a third-party image API before approval, bind that choice and its budget to the batch, and route all generated images through the existing review-free technical acceptance path.

**Architecture:** The startup confirmation remains the source of truth for user-visible configuration, while `approve-start` validates and seals the selected image provider into `approved_manifest`. The runner emits one of two provider-specific external actions but keeps download/generation outside the core runner; both actions return a local image to the existing `accept-image` boundary. Third-party API cost is tracked in a dedicated image ledger so it cannot be confused with DeepSeek/model or AutoDL video cost.

**Tech Stack:** Python 3 standard library (`argparse`, `dataclasses`, `decimal`, `hashlib`, `json`, `pathlib`), Pillow for offline image fixtures, pytest, Markdown skill documentation, ZIP release packaging.

## Global Constraints

- `image_provider` is required at startup and accepts exactly `gpt_web` or `third_party_api`; there is no default.
- The selected provider is immutable for the approved batch, and the runner never silently falls back to the other provider.
- GPT Web uses the currently signed-in browser session and does not enter the third-party API cost ledger.
- Third-party API configuration contains `api_name`, `base_url`, `model`, `api_key_env`, `unit_price_yuan`, and `batch_budget_yuan`; only the environment-variable name is persisted, never the secret value.
- Third-party image budget is separate from DeepSeek/model-call accounting and AutoDL video accounting.
- Both providers skip human/model image review and pass through the same local decode, dimension, SHA-256, and automatic promotion checks.
- A provider change requires a new startup configuration and budget approval.
- Tests must be offline-only and must not call GPT Web, a third-party image API, DeepSeek, or AutoDL.
- Preserve `release/product-video-pipeline-v1.7.0.zip` as historical output; publish this change as source/release version `1.7.1`.

## File Map

- Create `tests/test_image_provider_selection.py`: focused contract tests for required startup selection, provider routing, API configuration, budget reservation, idempotency, and shared acceptance.
- Modify `skill-package/product-video-pipeline/pipeline_policy.json`: declare the two permitted providers and the shared review-free image policy.
- Modify `skill-package/product-video-pipeline/scripts/pipeline_policy.py`: validate the new provider-policy shape and normalized third-party configuration.
- Modify `skill-package/product-video-pipeline/scripts/workflow_cli.py`: require provider selection when a batch is initialized and persist non-secret provider configuration in `启动确认单.json`.
- Modify `skill-package/product-video-pipeline/scripts/pipeline_runner.py`: bind provider configuration during approval, issue provider-specific image actions, account for image API cost, and accept either action through the shared image boundary.
- Modify `skill-package/product-video-pipeline/scripts/self_test.py`: replace the web-only assertions with two-provider startup/routing checks.
- Modify `skill-package/product-video-pipeline/SKILL.md` and `skill-package/product-video-pipeline/references/{startup-checklist.md,workflow.md,image-generation-routing.md,install.md,delivery-contract.md}`: document the required choice, no-fallback rule, API fields, and review-free shared path.
- Modify `skill-package/product-video-pipeline/VERSION`: bump to `1.7.1`.
- Modify `tests/test_pipeline_runtime_contract.py` and `tests/test_portable_skill_package.py`: adapt existing end-to-end and package assertions to the required provider argument and current release.
- Create `release/product-video-pipeline-v1.7.1.zip`: reproducible portable package containing the updated skill.

---

### Task 1: Require and validate the startup provider configuration

**Files:**
- Create: `tests/test_image_provider_selection.py`
- Modify: `skill-package/product-video-pipeline/pipeline_policy.json`
- Modify: `skill-package/product-video-pipeline/scripts/pipeline_policy.py`
- Modify: `skill-package/product-video-pipeline/scripts/workflow_cli.py:1185-1280`
- Modify: `tests/test_product_video_workflow.py`

**Interfaces:**
- Produces: `normalize_image_provider(value: object) -> str` in `pipeline_policy.py`.
- Produces: `normalize_image_api_config(value: object) -> dict[str, str]` in `pipeline_policy.py`, returning canonical decimal strings for both monetary fields.
- Produces: `_load_policy_module()` in `workflow_cli.py`, using `importlib.util` to load sibling `pipeline_policy.py` without requiring package installation.
- Produces: `initialize_batch(..., image_provider: str, image_api_config: object | None = None) -> BatchContext` with no provider default.
- Produces: `启动确认单.json.image_provider` and `启动确认单.json.image_api_config`; the latter is `{}` for GPT Web and the normalized non-secret mapping for third-party API.

- [ ] **Step 1: Add failing policy and initialization tests**

Add helpers that load `pipeline_policy.py` and `workflow_cli.py`, then add these concrete cases to `tests/test_image_provider_selection.py`:

```python
@pytest.mark.parametrize("value", [None, "", "automatic", "gpt_api"])
def test_image_provider_is_required_and_closed_to_unknown_values(value):
    policy = load_script("pipeline_policy.py")
    with pytest.raises(ValueError, match="图片渠道"):
        policy.normalize_image_provider(value)


@pytest.mark.parametrize("provider", ["gpt_web", "third_party_api"])
def test_policy_accepts_exactly_two_image_providers(provider):
    policy = load_script("pipeline_policy.py")
    assert policy.normalize_image_provider(provider) == provider


def test_third_party_config_requires_non_secret_fields():
    policy = load_script("pipeline_policy.py")
    valid = {
        "api_name": "Example Images",
        "base_url": "https://images.example.test/v1",
        "model": "image-v1",
        "api_key_env": "EXAMPLE_IMAGE_API_KEY",
        "unit_price_yuan": "0.20",
        "batch_budget_yuan": "5.00",
    }
    assert policy.normalize_image_api_config(valid) == valid
    for key in valid:
        broken = dict(valid)
        broken.pop(key)
        with pytest.raises(ValueError, match=key):
            policy.normalize_image_api_config(broken)
    with pytest.raises(ValueError, match="密钥|secret|明文"):
        policy.normalize_image_api_config({**valid, "api_key": "do-not-store"})
```

Add an initialization fixture with one product image and one cover reference, then assert that omitting `image_provider` raises `TypeError`, GPT Web persists `{}`, and third-party API persists the normalized six-field mapping.

- [ ] **Step 2: Run the focused tests and confirm the old web-only contract fails**

Run:

```powershell
python -m pytest tests/test_image_provider_selection.py -q
```

Expected: failures because `normalize_image_provider` and `normalize_image_api_config` do not exist, `initialize_batch` still defaults to `gpt_web`, and it rejects `third_party_api`.

- [ ] **Step 3: Replace the fixed provider policy with an allow-list**

Change the image block in `pipeline_policy.json` to:

```json
"image": {
  "allowed_providers": ["gpt_web", "third_party_api"],
  "human_review": false,
  "model_visual_review": false,
  "target_width": 2160,
  "target_height": 3840,
  "download_retries": 1
}
```

In `pipeline_policy.py`, add the following behavior next to existing amount validation and call it from `validate_policy`:

```python
IMAGE_PROVIDERS = ("gpt_web", "third_party_api")
IMAGE_API_FIELDS = (
    "api_name", "base_url", "model", "api_key_env",
    "unit_price_yuan", "batch_budget_yuan",
)


def normalize_image_provider(value: object) -> str:
    if not isinstance(value, str) or value not in IMAGE_PROVIDERS:
        raise ValueError("图片渠道必须明确选择 gpt_web 或 third_party_api")
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
    if not normalized["base_url"].startswith("https://"):
        raise ValueError("image_api_config.base_url 必须使用 https://")
    for key in IMAGE_API_FIELDS[4:]:
        amount = positive_amount(value.get(key), f"image_api_config.{key}")
        normalized[key] = str(amount)
    if Decimal(normalized["unit_price_yuan"]) > Decimal(normalized["batch_budget_yuan"]):
        raise ValueError("单张价格不能超过图片 API 批次预算")
    return normalized
```

Use the module's existing positive-decimal helper name instead of introducing a duplicate; if it is private, expose the same implementation as `positive_amount` and update its existing internal callers in the same edit. Validate that the configured `allowed_providers` equals `list(IMAGE_PROVIDERS)` and retain the existing `human_review is false` and `model_visual_review is false` checks.

- [ ] **Step 4: Make batch initialization explicit and persist only safe data**

Change the `initialize_batch` tail parameters and validation to this contract:

```python
def initialize_batch(
    *,
    # existing required arguments remain unchanged
    text_provider: str = "任务开始前确认",
    image_provider: str,
    image_api_config: object | None = None,
) -> BatchContext:
    policy_module = _load_policy_module()
    image_provider = policy_module.normalize_image_provider(image_provider)
    if image_provider == "third_party_api":
        normalized_image_api = policy_module.normalize_image_api_config(image_api_config)
    elif image_api_config not in (None, {}):
        raise ValueError("gpt_web 图片渠道不得携带第三方 API 配置")
    else:
        normalized_image_api = {}
```

If `workflow_cli.py` has no policy loader, add a local importlib loader following its existing sibling-script loading pattern. Add both values to `confirmation`:

```python
"image_provider": image_provider,
"image_api_config": normalized_image_api,
```

- [ ] **Step 5: Run the focused and workflow tests**

Run:

```powershell
python -m pytest tests/test_image_provider_selection.py tests/test_product_video_workflow.py -q
```

Expected: all selected tests pass after every `initialize_batch` test call supplies an explicit `image_provider="gpt_web"` or a complete third-party config.

- [ ] **Step 6: Commit the startup schema**

```powershell
git add tests/test_image_provider_selection.py skill-package/product-video-pipeline/pipeline_policy.json skill-package/product-video-pipeline/scripts/pipeline_policy.py skill-package/product-video-pipeline/scripts/workflow_cli.py tests/test_product_video_workflow.py
git commit -m "feat: require startup image provider selection"
```

---

### Task 2: Seal the provider choice and emit provider-specific image actions

**Files:**
- Modify: `tests/test_image_provider_selection.py`
- Modify: `tests/test_pipeline_runtime_contract.py`
- Modify: `skill-package/product-video-pipeline/scripts/pipeline_runner.py:443-487,1061-1130,1645-1798`

**Interfaces:**
- Consumes: `normalize_image_provider` and `normalize_image_api_config` from Task 1.
- Produces: `approve-start --image-provider {gpt_web,third_party_api} [--image-api-config PATH]`.
- Produces: `_approved_image_config(confirmation: dict[str, object], provider: str, config_path: Path | None) -> tuple[str, dict[str, str]]`.
- Produces: `_image_action_kind(provider: str) -> str`, returning `GPT_WEB_IMAGE_REQUIRED` or `THIRD_PARTY_IMAGE_REQUIRED`.
- Produces: image actions with `provider`, `action_id`, `video_id`, `artifact`, `prompt_path`, `output_path`, `reference_paths`, and `attempt`; API actions additionally contain `api_config` without a secret value.

- [ ] **Step 1: Write failing approval and routing tests**

Extend the runner fixture's `启动确认单.json` with an explicit provider. Add tests that invoke the real parser/main boundary:

```python
def test_approve_start_refuses_missing_image_provider(setup_batch, capsys):
    runner, _, batch, _, _ = setup_batch
    code = runner.main([
        "approve-start", "--batch", str(batch),
        "--approved-budget", "10", "--estimated-v01-total", "6",
    ])
    assert code != 0
    assert "image-provider" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("provider", "kind"),
    [("gpt_web", "GPT_WEB_IMAGE_REQUIRED"),
     ("third_party_api", "THIRD_PARTY_IMAGE_REQUIRED")],
)
def test_approved_provider_selects_exact_image_action(
    setup_batch, capsys, provider, kind, api_config_path
):
    action = approve_and_accept_content(
        setup_batch, capsys, provider,
        api_config_path if provider == "third_party_api" else None,
    )
    assert action["kind"] == kind
    assert action["provider"] == provider
```

Also assert that an API action exposes `api_key_env` but serialized state/action output does not contain the environment variable's secret value set by `monkeypatch.setenv`.

- [ ] **Step 2: Run the new routing tests and confirm failure**

Run:

```powershell
python -m pytest tests/test_image_provider_selection.py -k "approve_start or approved_provider or secret" -q
```

Expected: failures because `approve-start` lacks the new arguments and `next_action` always emits `GPT_WEB_IMAGE_REQUIRED`.

- [ ] **Step 3: Add approval CLI arguments and seal the selection**

Add parser arguments:

```python
approve.add_argument(
    "--image-provider",
    choices=("gpt_web", "third_party_api"),
    required=True,
)
approve.add_argument("--image-api-config", type=Path)
```

Implement `_approved_image_config` with these exact rules:

```python
def _approved_image_config(confirmation, provider, config_path):
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
```

Call this before changing state. Extend `_confirmation_manifest` so its digest includes `image_provider` and `image_api_config`, then store the same normalized values in `state.approved_manifest`. Because `validate_approved_manifest` recomputes the manifest, any edit to provider/config after approval must raise `PermissionError`.

- [ ] **Step 4: Route image actions without provider fallback**

Add:

```python
def _image_action_kind(provider: str) -> str:
    return {
        "gpt_web": "GPT_WEB_IMAGE_REQUIRED",
        "third_party_api": "THIRD_PARTY_IMAGE_REQUIRED",
    }[provider]
```

In `next_action`, read only `state.approved_manifest["image_provider"]`. Build the shared action fields once, set `kind` and `provider`, and for API actions add:

```python
action["api_config"] = dict(state.approved_manifest["image_api_config"])
```

Do not add an HTTP client and do not read the secret into the action. Reserve GPT Web with the existing `gpt_web_image` model category; API reservation is added in Task 3. If the approved provider is missing or invalid, transition to `BLOCKED` with a startup-configuration reason instead of choosing GPT Web.

- [ ] **Step 5: Generalize image receipts while preserving one acceptance path**

Add:

```python
IMAGE_ACTION_KINDS = {"GPT_WEB_IMAGE_REQUIRED", "THIRD_PARTY_IMAGE_REQUIRED"}


def _image_action_receipt(state: RunnerState, action_id: str | None) -> dict[str, object]:
    row = _action_receipt(state, action_id, expected_kind=None)
    if row.get("kind") not in IMAGE_ACTION_KINDS:
        raise ValueError("动作不是可接收的图片生成动作")
    if row.get("provider") != state.approved_manifest.get("image_provider"):
        raise PermissionError("图片结果渠道与已批准批次不一致")
    return row
```

Adjust `_action_receipt` so `expected_kind: str | None` skips only the equality check when it is `None`. Use `_image_action_receipt` in both `accept-image` and `image-failed`. Rename `accept_web_image` to `accept_generated_image` and update all internal/tests callers; its decode, resize, evidence, SHA-256, and promotion behavior must remain identical.

- [ ] **Step 6: Run runner contracts for both channels**

Run:

```powershell
python -m pytest tests/test_image_provider_selection.py tests/test_pipeline_runtime_contract.py -q
```

Expected: both providers produce the correct stable action, neither can accept the other's action, and both successfully promote a valid local PNG without a review gate.

- [ ] **Step 7: Commit provider-bound routing**

```powershell
git add tests/test_image_provider_selection.py tests/test_pipeline_runtime_contract.py skill-package/product-video-pipeline/scripts/pipeline_runner.py
git commit -m "feat: route images by approved startup provider"
```

---

### Task 3: Add a separate, idempotent third-party image cost ledger

**Files:**
- Modify: `tests/test_image_provider_selection.py`
- Modify: `skill-package/product-video-pipeline/scripts/pipeline_runner.py:135-215,330-360,905-960,1061-1130,1667-1800`

**Interfaces:**
- Consumes: provider-bound actions and normalized API config from Tasks 1-2.
- Produces: `RunnerState.image_budget_ledger: dict[str, dict[str, str]]`.
- Produces: `_store_reserved_action(state: RunnerState, action: dict[str, object], category: str) -> dict[str, object]`, the counter-free in-memory action primitive shared by model and image-API reservation; each caller performs one `save_state` after all related ledgers are updated.
- Produces: `_reserve_image_api_action(batch: Path, state: RunnerState, action: dict[str, object]) -> dict[str, object]`.
- Produces: `_settle_image_api_action(state: RunnerState, row: dict[str, object], outcome: str) -> None`, where outcome is `accepted`, `not_sent`, `sent`, or `unknown`.
- Produces: `image-failed --submission-state {not_sent,sent,unknown}`, defaulting to `unknown`.

- [ ] **Step 1: Add failing ledger and idempotency tests**

Add these scenarios:

```python
def test_third_party_next_reserves_once_and_reuses_action(api_batch):
    runner, policy, batch, state = api_batch
    first = runner.next_action(batch, state, policy)
    second = runner.next_action(batch, state, policy)
    assert second == first
    assert state.image_budget_ledger[first["action_id"]]["status"] == "reserved"
    assert state.image_budget_ledger[first["action_id"]]["cost"] == "0.20"
    assert len(state.image_budget_ledger) == 1


def test_gpt_web_never_touches_image_api_ledger(web_batch):
    runner, policy, batch, state = web_batch
    assert runner.next_action(batch, state, policy)["kind"] == "GPT_WEB_IMAGE_REQUIRED"
    assert state.image_budget_ledger == {}


def test_api_budget_exhaustion_emits_no_new_paid_action(api_batch):
    runner, policy, batch, state = api_batch
    state.approved_manifest["image_api_config"]["batch_budget_yuan"] = "0.20"
    first = runner.next_action(batch, state, policy)
    settle_valid_image(runner, batch, first)
    state.pending_action = None
    action = runner.next_action(batch, state, policy)
    assert action["kind"] == "BLOCKED"
    assert "图片 API" in action["reason"] and "预算" in action["reason"]
```

Add parameterized failure settlement checks: `not_sent` removes/releases the reservation, `sent` becomes `spent`, `unknown` becomes `unknown`, and retrying the identical failure receipt does not settle twice. For `unknown`, also assert that state becomes `BLOCKED`, the original request identity remains in `model_actions` and `image_budget_ledger`, and the next call returns `BLOCKED` instead of a replacement paid action.

- [ ] **Step 2: Run the ledger tests and verify failure**

Run:

```powershell
python -m pytest tests/test_image_provider_selection.py -k "ledger or budget or submission_state" -q
```

Expected: failures because the state has no image ledger and `image-failed` has no submission-state argument.

- [ ] **Step 3: Add the durable image ledger schema**

Add this dataclass field without changing `schema_version` so old v1.7.0 state files load through the dataclass default:

```python
image_budget_ledger: dict[str, dict[str, str]] = field(default_factory=dict)
```

Validate every entry has status in `{"reserved", "spent", "unknown", "released"}`, a positive canonical `cost`, an `action_id` matching its key, and provider `third_party_api`. Do not merge this ledger into the existing AutoDL `budget_ledger` or model counters.

- [ ] **Step 4: Reserve API cost atomically and fail closed at the budget ceiling**

First extract the final action-ID/storage portion of `_reserve_action` into this counter-free helper and have `_reserve_action` call it after its existing model/GPT-Web counters are charged:

```python
def _store_reserved_action(state, action, category):
    action = {**action, "action_id": uuid.uuid4().hex}
    state.model_actions[action["action_id"]] = {
        **action,
        "category": category,
        "status": "reserved",
        "reserved_at": _now(),
    }
    state.pending_action = action
    return action
```

Change `_reserve_action` to call this helper and then `save_state(batch, state)` once, preserving its observable behavior. Then implement `_reserve_image_api_action` so it:

1. Returns `state.pending_action` unchanged when the same reserved action already exists.
2. Reads `unit_price_yuan` and `batch_budget_yuan` from the sealed manifest.
3. Sums entries whose status is `reserved`, `spent`, or `unknown`; `released` entries do not consume budget.
4. Refuses a reservation when `used + unit_price > batch_budget`.
5. Calls `_store_reserved_action(..., category="third_party_image_api")` once, writes this ledger entry, then calls `save_state(batch, state)` once before returning:

```python
state.image_budget_ledger[action["action_id"]] = {
    "action_id": action["action_id"],
    "provider": "third_party_api",
    "cost": str(unit_price),
    "status": "reserved",
    "at": _now(),
}
```

The action itself must expose `estimated_cost_yuan` and `remaining_image_budget_yuan`. In `next_action`, call `_reserve_image_api_action` only for `third_party_api`; retain `_reserve_action(..., "gpt_web_image")` for GPT Web.

- [ ] **Step 5: Settle accepted and failed actions exactly once**

Implement:

```python
def _settle_image_api_action(state, row, outcome):
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
```

Call it with `accepted` only after `accept_generated_image` succeeds. On technical acceptance failure after an API result exists, settle as `sent`. Add:

```python
image_failed.add_argument(
    "--submission-state",
    choices=("not_sent", "sent", "unknown"),
    default="unknown",
)
```

Use that value for API failures; GPT Web ignores it. Keep `_finish_action` receipt digest idempotency intact. When an API failure has `submission_state == "unknown"`, call `_finish_action`, retain the ledger/request identifiers, and then transition to `BLOCKED` with reason `图片 API 提交状态未知，已停止自动重提`; no subsequent `next` may reserve a replacement action until an operator resolves the external submission and starts a newly approved recovery scope.

- [ ] **Step 6: Run all focused state-machine tests**

Run:

```powershell
python -m pytest tests/test_image_provider_selection.py tests/test_pipeline_runtime_contract.py -q
```

Expected: all tests pass, repeated `next` never double-reserves, repeated receipts never double-settle, uncertain submissions consume budget, and GPT Web leaves the API ledger empty.

- [ ] **Step 7: Commit cost isolation**

```powershell
git add tests/test_image_provider_selection.py skill-package/product-video-pipeline/scripts/pipeline_runner.py
git commit -m "feat: isolate third party image api budget"
```

---

### Task 4: Update startup UX, operator documentation, and self-test

**Files:**
- Modify: `skill-package/product-video-pipeline/SKILL.md`
- Modify: `skill-package/product-video-pipeline/references/startup-checklist.md`
- Modify: `skill-package/product-video-pipeline/references/workflow.md`
- Modify: `skill-package/product-video-pipeline/references/image-generation-routing.md`
- Modify: `skill-package/product-video-pipeline/references/install.md`
- Modify: `skill-package/product-video-pipeline/references/delivery-contract.md`
- Modify: `skill-package/product-video-pipeline/scripts/self_test.py`
- Modify: `tests/test_portable_skill_package.py`

**Interfaces:**
- Consumes: CLI/action/config contracts from Tasks 1-3.
- Produces: the exact startup prompt choice `GPT 网页端` / `第三方 API` before any scan, batch creation, price query, media generation, dry-run, or paid call.
- Produces: operator instructions for fulfilling both external action kinds and returning the downloaded local image through `accept-image`.

- [ ] **Step 1: Replace web-only documentation assertions with the approved two-channel rules**

Add explicit assertions in `tests/test_portable_skill_package.py` that the skill and routed documentation contain all of:

```python
required_phrases = (
    "GPT 网页端",
    "第三方 API",
    "必须选择",
    "批次内锁定",
    "禁止自动切换",
    "不进行人工图片审核",
    "不进行模型视觉审核",
    "api_key_env",
    "图片 API 批次预算",
)
```

Assert that startup displays the provider choice inside the existing “你需要提供的内容 / 本次配置明细 / 请你回复” three-block confirmation, and that third-party API documentation names all six config fields. Remove assertions whose intended meaning is “GPT Web is the sole channel”; retain assertions that forbid server-side OpenAI API usage when `gpt_web` is selected.

- [ ] **Step 2: Run documentation contracts and confirm failure**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "startup or image_generation or compact_pipeline_policy" -q
```

Expected: failures identify the existing web-only copy and missing API startup fields.

- [ ] **Step 3: Rewrite the startup and routing instructions**

Update `startup-checklist.md` so the first unanswered required item is exactly:

```markdown
- 生图渠道（必须二选一）：`GPT 网页端` / `第三方 API`
  - 选择 `GPT 网页端`：确认使用当前已登录会话。
  - 选择 `第三方 API`：同时提供 API 名称、Base URL、模型、密钥环境变量名、单张价格、图片 API 批次预算。
```

State directly below it that no operational step starts until this choice and, when applicable, all API fields are confirmed. In the configuration summary show the selected provider and a separate image API budget line; never render or request a secret value.

Rewrite `image-generation-routing.md` around this deterministic flow:

```text
启动必选渠道 -> 批次批准并锁定 -> 签发对应外部动作
-> 外部渠道生成并下载 -> accept-image -> 统一本地技术检查
-> 自动晋升 -> 下一节点
```

Document `GPT_WEB_IMAGE_REQUIRED` as browser-session work and `THIRD_PARTY_IMAGE_REQUIRED` as host/API-adapter work. State that neither path includes image content review and neither may switch to the other after an error.

- [ ] **Step 4: Align the skill entrypoint, workflow, install, and delivery contract**

In `SKILL.md`, replace “GPT Web sole image channel” with the startup-required two-choice rule and list both runtime action kinds. In `workflow.md`, place provider selection before scanning/creation and keep `accept-image` as the shared resume command. In `install.md`, document setting the environment variable named by `api_key_env` without showing a real credential. In `delivery-contract.md`, require the provider and API cost ledger summary in final batch reporting when third-party API was selected.

- [ ] **Step 5: Update the offline self-test**

Replace the sole-provider check in `self_test.py` with checks that:

```python
assert policy["image"]["allowed_providers"] == ["gpt_web", "third_party_api"]
assert policy["image"]["human_review"] is False
assert policy["image"]["model_visual_review"] is False
```

Build one temporary approved state for each provider, call `next_action`, assert the provider-specific kind, and stop before any external execution. The third-party fixture uses `https://images.example.test/v1`, a fake environment-variable name, and offline monetary values only.

- [ ] **Step 6: Run docs and self-test**

Run:

```powershell
python skill-package/product-video-pipeline/scripts/self_test.py
python -m pytest tests/test_portable_skill_package.py -q
```

Expected: self-test exits 0 with its normal success marker; all package contract tests pass without network access.

- [ ] **Step 7: Commit operator-facing behavior**

```powershell
git add skill-package/product-video-pipeline/SKILL.md skill-package/product-video-pipeline/references skill-package/product-video-pipeline/scripts/self_test.py tests/test_portable_skill_package.py
git commit -m "docs: require image provider choice at startup"
```

---

### Task 5: Version, package, and verify the offline release

**Files:**
- Modify: `skill-package/product-video-pipeline/VERSION`
- Modify: `tests/test_pipeline_runtime_contract.py`
- Modify: `tests/test_portable_skill_package.py`
- Create: `release/product-video-pipeline-v1.7.1.zip`

**Interfaces:**
- Consumes: all runtime and documentation contracts from Tasks 1-4.
- Produces: portable release `product-video-pipeline-v1.7.1.zip` whose root directory is `product-video-pipeline/` and whose `VERSION` is `1.7.1`.

- [ ] **Step 1: Add the release-version regression first**

Update package tests to assert:

```python
assert (SKILL_ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.7.1"
archive = REPO_ROOT / "release" / "product-video-pipeline-v1.7.1.zip"
assert archive.is_file()
with zipfile.ZipFile(archive) as bundle:
    assert bundle.read("product-video-pipeline/VERSION").decode().strip() == "1.7.1"
    assert "product-video-pipeline/scripts/pipeline_runner.py" in bundle.namelist()
```

Keep the existing v1.7.0 archive untouched. Update every real `approve-start` invocation in runtime tests to include `--image-provider gpt_web`; third-party-specific tests continue to pass the config path and fake environment variable.

- [ ] **Step 2: Run the full suite before the version/package change**

Run:

```powershell
python -m pytest -q
```

Expected: only the new `VERSION == 1.7.1` and missing-v1.7.1-archive assertions fail; runtime failures indicate a missed explicit provider argument and must be fixed before packaging.

- [ ] **Step 3: Bump the source version and build a clean archive**

Change `skill-package/product-video-pipeline/VERSION` to exactly:

```text
1.7.1
```

Build the archive from the contents of `skill-package/product-video-pipeline` with the ZIP prefix `product-video-pipeline/`. Exclude `__pycache__/`, `*.pyc`, `.pytest_cache/`, real `.env` files, logs, temporary media, and all credential material. This repository has no release-building script, so use this PowerShell command from the repository root:

```powershell
$source = Resolve-Path 'skill-package/product-video-pipeline'
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ('product-video-pipeline-v1.7.1-' + [guid]::NewGuid())
$target = Join-Path $stage 'product-video-pipeline'
New-Item -ItemType Directory -Path $target -Force | Out-Null
Get-ChildItem -LiteralPath $source -Recurse -File | Where-Object {
    $_.FullName -notmatch '[\\/](__pycache__|\.pytest_cache)[\\/]' -and
    $_.Extension -ne '.pyc' -and $_.Name -ne '.env'
} | ForEach-Object {
    $relative = $_.FullName.Substring($source.Path.Length).TrimStart('\')
    $destination = Join-Path $target $relative
    New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $destination
}
Compress-Archive -LiteralPath $target -DestinationPath 'release/product-video-pipeline-v1.7.1.zip' -Force
```

After resolving and printing `$stage`, verify it is beneath `[System.IO.Path]::GetTempPath()` before removing it with `Remove-Item -LiteralPath $stage -Recurse -Force`.

- [ ] **Step 4: Inspect the archive for secrets and incorrect roots**

Run:

```powershell
python -c "import zipfile,pathlib; p=pathlib.Path('release/product-video-pipeline-v1.7.1.zip'); z=zipfile.ZipFile(p); names=z.namelist(); assert names and all(n.startswith('product-video-pipeline/') for n in names); forbidden=('.env','__pycache__','.pyc','.pytest_cache'); assert not any(any(x in n for x in forbidden) for n in names); print(len(names))"
```

Expected: prints a positive file count and exits 0. Then search both source and archive-extracted text for credential-shaped assignments; allow only documented placeholder environment-variable names, never values.

Run the credential-shape scan without printing any matched value:

```powershell
python -c "import pathlib,re,zipfile; roots=list(pathlib.Path('skill-package/product-video-pipeline').rglob('*')); bad=[]; pat=re.compile(rb'(?i)(api[_-]?key|authorization|bearer|secret)\s*[:=]\s*[\"\x27]?[A-Za-z0-9_./+-]{16,}'); bad += [str(p) for p in roots if p.is_file() and p.name != '.env' and pat.search(p.read_bytes())]; z=zipfile.ZipFile('release/product-video-pipeline-v1.7.1.zip'); bad += [n for n in z.namelist() if not n.endswith('/') and pat.search(z.read(n))]; assert not bad, 'credential-shaped values found in: ' + ', '.join(bad); print('credential scan passed')"
```

Expected: prints `credential scan passed` and exits 0; the diagnostic exposes filenames only, not possible secret contents.

- [ ] **Step 5: Run final offline verification**

Run:

```powershell
python -m pytest -q
python skill-package/product-video-pipeline/scripts/self_test.py
python -m zipfile -t release/product-video-pipeline-v1.7.1.zip
git diff --check
```

Expected: the full pytest suite passes; self-test succeeds; ZIP reports `Done testing`; `git diff --check` prints nothing. No command may require network access or consume a paid service.

- [ ] **Step 6: Record checksum and commit the release**

Run:

```powershell
Get-FileHash -Algorithm SHA256 'release/product-video-pipeline-v1.7.1.zip'
git add skill-package/product-video-pipeline/VERSION tests/test_pipeline_runtime_contract.py tests/test_portable_skill_package.py release/product-video-pipeline-v1.7.1.zip
git commit -m "release: package product video pipeline v1.7.1"
```

Record the printed SHA-256 in the final handoff together with the exact pytest pass count and the isolated branch/worktree path.

## Plan Self-Review

- Spec coverage: startup choice, no default, batch immutability, no fallback, GPT Web session use, six API fields, secret-name-only persistence, separate image budget, shared technical checks, no review, new approval on provider change, offline tests, and release packaging are each mapped to Tasks 1-5.
- Placeholder scan: the plan contains no deferred implementation markers; every code-changing step names exact behavior, files, commands, and expected results.
- Type consistency: provider values, six config keys, action kinds, CLI argument names, ledger statuses, settlement outcomes, and version `1.7.1` are consistent across all tasks.
