# Product Video API Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a `配置api` setup flow that securely stores and replaces the product-video skill's API settings in permanent Windows user environment variables without starting or authorizing media generation.

**Architecture:** The repository copy under `skill-package/product-video-pipeline` is the versioned source package. This plan integrates the configuration feature onto remote version `1.8.0` and releases source version `1.8.1`; the installed copy under `C:/Users/Administrator/.agents/skills/product-video-pipeline` is deployed and verified separately. A focused `api_config.py` owns configuration schemas, masking, registry-backed persistence, hidden terminal input, status output, and rollback; `autodl_h3.py` and the pipeline runner read that persistent store as a fallback. Skill instructions route `配置api` to a dedicated reference document and keep it separate from product-video startup.

**Tech Stack:** Python 3 standard library (`argparse`, `getpass`, `json`, `os`, `winreg`, `ctypes`), Markdown skill instructions, existing no-network `self_test.py`.

## Global Constraints

- Never put a complete API key in chat, command-line arguments, Markdown, JSON, project files, or logs.
- Store secrets only in Windows current-user environment variables.
- `配置api` never starts a product batch, scans product files, generates media, or authorizes a paid request.
- Connection validation may use only a documented non-billable endpoint; otherwise report `已保存，未联网验证`.
- Replacing one API category must preserve all other categories and preserve the old category values when validation or persistence fails.
- Release the repository package as version `1.8.1` without regressing the `1.8.0` state machine.

---

### Task 1: Add failing configuration-contract tests

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/self_test.py`
- Modify: `C:/Users/Administrator/.agents/skills/product-video-pipeline/scripts/self_test.py`

**Interfaces:**
- Consumes: existing `self_test.py` document and CLI checks.
- Produces: failing assertions for `api_config.py`, `配置api` routing text, key masking, three API schemas, in-memory atomic replacement, and AutoDL persistent-value fallback.

- [x] **Step 1: Add required-file and routing assertions**

Add `references/api-configuration.md` and `scripts/api_config.py` to `required`. Require `配置api`, `只进入 API 配置向导`, `Windows 当前用户`, and `不得触发产品视频启动清单` in the appropriate Markdown files.

- [x] **Step 2: Add pure behavior tests**

Load `api_config.py` with `importlib.util`, then assert:

```python
assert api_config.mask_secret("12345678") == "****5678"
assert api_config.mask_secret("") == "未配置"
assert set(api_config.CONFIG_SCHEMAS) == {"autodl", "image", "text"}

store = api_config.MemoryStore({"AUTODL_API_KEY": "old-key"})
api_config.save_category("autodl", {"AUTODL_API_KEY": "new-key", "AUTODL_AUTH_SCHEME": "bearer"}, store)
assert store.get("AUTODL_API_KEY") == "new-key"
```

Add a failing store whose `set_many` raises and assert the prior values remain unchanged.

- [x] **Step 3: Run the tests and confirm RED**

Run:

```powershell
$env:PYTHONUTF8='1'
python skill-package/product-video-pipeline/scripts/self_test.py
```

Expected: FAIL because `scripts/api_config.py` or `references/api-configuration.md` does not exist.

### Task 2: Implement the local persistent API configuration tool

**Files:**
- Create: `skill-package/product-video-pipeline/scripts/api_config.py`
- Create: `skill-package/product-video-pipeline/references/api-configuration.md`
- Create: `C:/Users/Administrator/.agents/skills/product-video-pipeline/scripts/api_config.py`
- Create: `C:/Users/Administrator/.agents/skills/product-video-pipeline/references/api-configuration.md`

**Interfaces:**
- Produces: `CONFIG_SCHEMAS`, `mask_secret(value: str) -> str`, `MemoryStore`, `WindowsUserEnvironmentStore`, `save_category(category: str, values: dict[str, str], store) -> None`, `get_config_value(name: str) -> str | None`, and CLI commands `status` and `configure --category {autodl,image,text}`.
- Consumes: hidden input from `getpass.getpass`; non-secret provider/base URL/model fields from interactive `input()`.

- [x] **Step 1: Implement schemas and masking**

Define exact mappings:

```python
CONFIG_SCHEMAS = {
    "autodl": ("AUTODL_API_KEY", "AUTODL_AUTH_SCHEME"),
    "image": ("PRODUCT_VIDEO_IMAGE_API_PROVIDER", "PRODUCT_VIDEO_IMAGE_API_BASE_URL", "PRODUCT_VIDEO_IMAGE_API_MODEL", "PRODUCT_VIDEO_IMAGE_API_KEY"),
    "text": ("PRODUCT_VIDEO_TEXT_API_PROVIDER", "PRODUCT_VIDEO_TEXT_API_BASE_URL", "PRODUCT_VIDEO_TEXT_API_MODEL", "PRODUCT_VIDEO_TEXT_API_KEY"),
}
```

`mask_secret` returns `未配置` for empty values and otherwise `****` plus the last four characters.

- [x] **Step 2: Implement storage and rollback**

`WindowsUserEnvironmentStore` reads and writes `HKCU\\Environment`, updates `os.environ`, and broadcasts `WM_SETTINGCHANGE`. `set_many` snapshots old values, writes the complete category, and restores the snapshot if any write fails. `MemoryStore` implements the same `get` and `set_many` interface for offline tests.

- [x] **Step 3: Implement interactive configuration**

`configure --category autodl` asks for `bearer/raw` and reads the key with `getpass`; image/text ask provider, HTTPS base URL, model, and hidden key. Validate required non-empty fields, `https://` base URLs, and allowed AutoDL schemes before calling `save_category`.

- [x] **Step 4: Implement safe status output**

`status` prints all three categories with required/optional labels, non-secret fields, and masked keys. It must never serialize raw key values.

- [x] **Step 5: Document operator flow**

The reference must instruct the agent to show status, ask which category to configure, start the interactive script in a visible terminal, avoid chat key collection, and report `已保存，未联网验证` when no safe validation endpoint is available.

- [x] **Step 6: Run tests and confirm GREEN for the tool**

Run both copies of `self_test.py`; expected: configuration helper assertions pass, with no network access and no persistent test credentials written.

### Task 3: Route the new trigger and preserve authorization boundaries

**Files:**
- Modify: both copies of `SKILL.md`
- Modify: both copies of `references/startup-checklist.md`
- Modify: both copies of `references/install.md`
- Modify: both copies of `references/image-generation-routing.md`

**Interfaces:**
- Consumes: exact trigger `配置api` and the new API configuration reference.
- Produces: deterministic separation between API configuration and product-video startup.

- [x] **Step 1: Extend discovery and trigger contract**

Add `配置api` to the frontmatter description. State that it enters the API configuration wizard only and is not one of the product-video batch triggers.

- [x] **Step 2: Add required routing**

Before product-task routing, require reading `references/api-configuration.md`, showing masked status and the required/optional API list, then asking which category to configure. Explicitly prohibit startup checklist display, batch initialization, directory scan, media generation, price lookup, dry-run, or paid calls from this trigger.

- [x] **Step 3: Align startup and installation docs**

Keep normal product startup from repeatedly asking for API configuration. If a required API is absent, direct the user to `配置api`; do not request a full key in chat. Document the permanent variable names and replacement behavior in `install.md`.

- [x] **Step 4: Verify routing assertions pass**

Run both self-tests and search maintained Markdown for contradictory instructions that request keys in chat or treat `配置api` as a product-video trigger.

### Task 4: Make AutoDL consume permanent user configuration

**Files:**
- Modify: both copies of `scripts/autodl_h3.py`
- Modify: both copies of `scripts/self_test.py`

**Interfaces:**
- Consumes: `get_config_value(name)` from sibling `api_config.py`.
- Produces: AutoDL key and auth scheme resolution from current process environment first, then Windows current-user environment.

- [x] **Step 1: Add failing fallback tests**

Patch the imported config reader in-memory and assert AutoDL resolves `AUTODL_API_KEY` and `AUTODL_AUTH_SCHEME` when absent from `os.environ`.

- [x] **Step 2: Verify RED**

Run the package self-test; expected: FAIL because `autodl_h3.py` still reads only `os.environ`.

- [x] **Step 3: Implement fallback resolution**

Import `get_config_value`; replace direct `os.environ.get` calls with a small `_config_value` helper. Parser auth default becomes `_config_value("AUTODL_AUTH_SCHEME") or "bearer"`; submit/query key lookup uses `_config_value("AUTODL_API_KEY")`.

- [x] **Step 4: Verify GREEN**

Run both self-tests and `python -m py_compile` for `api_config.py`, `autodl_h3.py`, `workflow_cli.py`, and `self_test.py`.

### Task 5: Reconcile with remote 1.8.0, release version 1.8.1, and verify

**Files:**
- Modify: both copies of `VERSION`
- Reconcile: repository feature changes with all remote `1.8.0` state-machine and policy files.

**Interfaces:**
- Consumes: passing package behavior.
- Produces: a validated repository skill tree and release archive at version `1.8.1`.

- [x] **Step 1: Preserve the existing three-choice image-channel behavior**

Apply the three equal image choices to the remote `1.8.0` policy and runner: no default, required `--image-provider`, no automatic channel switching, and legacy `gpt_web` batch compatibility.

- [x] **Step 2: Bump both versions**

Set the repository `VERSION` to `1.8.1` and build `release/product-video-pipeline-v1.8.1.zip`.

- [x] **Step 3: Run complete verification**

Run:

```powershell
$env:PYTHONUTF8='1'
python skill-package/product-video-pipeline/scripts/self_test.py
python C:/Users/Administrator/.agents/skills/product-video-pipeline/scripts/self_test.py
python -m py_compile skill-package/product-video-pipeline/scripts/*.py
python C:/Users/Administrator/.codex/skills/.system/skill-creator/scripts/quick_validate.py skill-package/product-video-pipeline
python C:/Users/Administrator/.codex/skills/.system/skill-creator/scripts/quick_validate.py C:/Users/Administrator/.agents/skills/product-video-pipeline
```

Expected: both self-tests report no network/no charge success, compilation exits `0`, and both validators report `Skill is valid!`.

- [x] **Step 4: Compare runtime-critical files**

Verify the repository tree and release archive contain matching `SKILL.md`, `VERSION`, `references/api-configuration.md`, `scripts/api_config.py`, `scripts/autodl_h3.py`, and `scripts/self_test.py`. Installed-runtime synchronization is a separate deployment check and must not be claimed by this repository-only release step.

- [x] **Step 5: Commit only in-scope repository files**

Stage the plan, package skill changes, and relevant tests explicitly; do not stage unrelated dirty-worktree files. Commit with `feat: add persistent product video API configuration`.
