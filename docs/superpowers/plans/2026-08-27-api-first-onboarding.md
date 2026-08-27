# API-First Skill Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AutoDL API setup and no-charge verification the mandatory first-use gate before any product-video workflow begins.

**Architecture:** Add a small no-network `api_setup.py` readiness checker that reads only environment variables and emits secret-free JSON. Route `SKILL.md`, installation guidance, and the startup checklist through this checker before product scanning; retain the existing paid-operation confirmation as a separate gate.

**Tech Stack:** Python 3.9+, `argparse`, `json`, `os`, `pathlib`, pytest, Markdown Agent Skill instructions.

## Global Constraints

- API Key is read only from `AUTODL_API_KEY`.
- Authentication scheme is read from `AUTODL_AUTH_SCHEME`; allowed values are `raw` and `bearer`, with `raw` as the documented default.
- Never print or persist the API Key in logs, JSON, errors, state files, or chat.
- API readiness checks and dry-runs must not access the network or create charges.
- API readiness does not authorize a paid submission; paid submission still requires explicit budget approval.
- While API setup is incomplete, do not scan product images, initialize batches, or request product workflow details.

---

### Task 1: Secret-Free API Readiness Checker

**Files:**
- Create: `skill-package/product-video-pipeline/scripts/api_setup.py`
- Modify: `skill-package/product-video-pipeline/scripts/autodl_h3.py`
- Modify: `tests/test_portable_skill_package.py`

**Interfaces:**
- Consumes: environment variables `AUTODL_API_KEY` and `AUTODL_AUTH_SCHEME`.
- Produces: `check_api_setup(environment: Mapping[str, str]) -> Dict[str, object]` and CLI JSON with `ready`, `auth_scheme`, `checked_at_utc`, `network_used`, `billable`, and `next_action`; exit code `0` when ready and `2` otherwise. `autodl_h3.py` uses `raw` as its default auth scheme.

- [ ] **Step 1: Add failing readiness tests**

Add these tests to `tests/test_portable_skill_package.py`:

```python
def test_api_setup_blocks_missing_key_without_leaking_secrets():
    setup = load_script("api_setup.py")
    result = setup.check_api_setup({})
    assert result == {
        "ready": False,
        "auth_scheme": "raw",
        "checked_at_utc": result["checked_at_utc"],
        "network_used": False,
        "billable": False,
        "next_action": "configure_autodl_api_key",
    }


def test_api_setup_accepts_key_and_never_returns_it():
    setup = load_script("api_setup.py")
    secret = "test-super-secret-token"
    result = setup.check_api_setup({
        "AUTODL_API_KEY": secret,
        "AUTODL_AUTH_SCHEME": "raw",
    })
    assert result["ready"] is True
    assert result["auth_scheme"] == "raw"
    assert result["checked_at_utc"].endswith("+00:00")
    assert secret not in json.dumps(result, ensure_ascii=False)


def test_api_setup_rejects_invalid_auth_scheme():
    setup = load_script("api_setup.py")
    result = setup.check_api_setup({
        "AUTODL_API_KEY": "secret",
        "AUTODL_AUTH_SCHEME": "token",
    })
    assert result["ready"] is False
    assert result["next_action"] == "configure_auth_scheme"
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
pytest -q tests/test_portable_skill_package.py -k api_setup
```

Expected: FAIL because `scripts/api_setup.py` does not exist.

- [ ] **Step 3: Implement the minimal checker**

Create `scripts/api_setup.py` with:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence


def check_api_setup(environment: Mapping[str, str]) -> Dict[str, object]:
    auth_scheme = environment.get("AUTODL_AUTH_SCHEME", "raw").strip().lower()
    key_present = bool(environment.get("AUTODL_API_KEY", "").strip())
    checked_at_utc = datetime.now(timezone.utc).isoformat()
    if auth_scheme not in {"raw", "bearer"}:
        return {
            "ready": False,
            "auth_scheme": auth_scheme,
            "checked_at_utc": checked_at_utc,
            "network_used": False,
            "billable": False,
            "next_action": "configure_auth_scheme",
        }
    return {
        "ready": key_present,
        "auth_scheme": auth_scheme,
        "checked_at_utc": checked_at_utc,
        "network_used": False,
        "billable": False,
        "next_action": "run_dry_run" if key_present else "configure_autodl_api_key",
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="检查 AutoDL API 首次接入状态（不联网、不扣费）")
    parser.add_argument("--state", type=Path)
    args = parser.parse_args(argv)
    result = check_api_setup(os.environ)
    if args.state:
        _write_json(args.state, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
```

Also change the `autodl_h3.py` parser default from `"bearer"` to `"raw"`, and add a parser test asserting `build_parser().parse_args(["submit", "--payload", "payload.json"]).auth_scheme == "raw"` when the environment variable is absent.

- [ ] **Step 4: Run readiness tests and verify GREEN**

Run:

```powershell
pytest -q tests/test_portable_skill_package.py -k api_setup
```

Expected: `3 passed`.

- [ ] **Step 5: Commit the checker**

```powershell
git add -- skill-package/product-video-pipeline/scripts/api_setup.py skill-package/product-video-pipeline/scripts/autodl_h3.py tests/test_portable_skill_package.py
git commit -m "feat: add secret-free AutoDL setup gate"
```

### Task 2: Route Installation and First Invocation Through API Setup

**Files:**
- Modify: `skill-package/product-video-pipeline/SKILL.md`
- Modify: `skill-package/product-video-pipeline/references/install.md`
- Modify: `skill-package/product-video-pipeline/references/startup-checklist.md`
- Modify: `tests/test_portable_skill_package.py`

**Interfaces:**
- Consumes: the Task 1 CLI command `python scripts/api_setup.py` and its `ready` result.
- Produces: an instruction-level gate that stops before product scanning until setup and dry-run are complete.

- [ ] **Step 1: Add a failing routing test**

Add:

```python
def test_skill_requires_api_setup_before_product_workflow():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    install = (SKILL_ROOT / "references" / "install.md").read_text(encoding="utf-8")
    startup = (SKILL_ROOT / "references" / "startup-checklist.md").read_text(encoding="utf-8")
    assert "节点 0：API 接入门禁" in skill
    assert skill.index("节点 0：API 接入门禁") < skill.index("产品素材")
    assert "python scripts/api_setup.py" in install
    assert "API 未就绪时" in startup
    assert "不得扫描产品" in startup
```

- [ ] **Step 2: Run the routing test and verify RED**

Run:

```powershell
pytest -q tests/test_portable_skill_package.py::test_skill_requires_api_setup_before_product_workflow
```

Expected: FAIL because the API-first wording is absent.

- [ ] **Step 3: Add the minimal routing instructions**

In `SKILL.md`, place this before current required routing:

```markdown
## 节点 0：API 接入门禁

每次调用先运行 `python scripts/api_setup.py`。未就绪时，第一条业务回复只引导用户安全配置 AutoDL API，不询问产品路径、卖点或批次参数，不扫描产品，也不创建批次。密钥不得粘贴到聊天；只使用 `AUTODL_API_KEY` 环境变量。检查就绪后先执行不联网、不扣费的 dry-run；两项都通过才进入产品素材和启动确认流程。API 就绪不代表用户已授权付费。
```

In `references/install.md`, add an “安装后立即接入 API” section containing the checker command, Windows environment-variable guidance that does not echo the key into chat, and the dry-run command from `references/autodl-h3.md`.

In `references/startup-checklist.md`, add:

```markdown
## API 前置门禁

API 未就绪时，暂停在接入步骤，不得扫描产品、询问产品批次参数或创建输出目录。只有 `api_setup.py` 返回 `ready: true` 且 dry-run 通过后，才展示下方任务启动确认单。
```

- [ ] **Step 4: Run the routing test and verify GREEN**

Run:

```powershell
pytest -q tests/test_portable_skill_package.py::test_skill_requires_api_setup_before_product_workflow
```

Expected: PASS.

- [ ] **Step 5: Commit the routing change**

```powershell
git add -- skill-package/product-video-pipeline/SKILL.md skill-package/product-video-pipeline/references/install.md skill-package/product-video-pipeline/references/startup-checklist.md tests/test_portable_skill_package.py
git commit -m "docs: require AutoDL setup before product workflow"
```

### Task 3: Package Self-Test and Regression Verification

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/self_test.py`
- Modify: `tests/test_portable_skill_package.py`

**Interfaces:**
- Consumes: `scripts/api_setup.py` from Task 1 and existing `autodl_h3.py submit --dry-run`.
- Produces: a package self-test proving the setup gate is present, secret-free, offline, and non-billable.

- [ ] **Step 1: Add a failing self-test integration assertion**

Add `"scripts/api_setup.py"` to the existing `required` set in `test_skill_package_contains_required_portable_resources`, then add this test before modifying `self_test.py`:

```python
def test_self_test_executes_api_setup_gate():
    source = (SKILL_ROOT / "scripts" / "self_test.py").read_text(encoding="utf-8")
    assert 'SKILL_ROOT / "scripts" / "api_setup.py"' in source
    assert "test-self-test-secret" in source
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
pytest -q tests/test_portable_skill_package.py::test_self_test_executes_api_setup_gate
```

Expected: FAIL because `self_test.py` does not execute the API setup checker.

- [ ] **Step 3: Extend package self-test**

Update `self_test.py` to require `scripts/api_setup.py`, run it in a child environment containing `AUTODL_API_KEY=test-self-test-secret` and `AUTODL_AUTH_SCHEME=raw`, parse JSON, assert `ready is True`, `network_used is False`, `billable is False`, and assert the secret is absent from stdout.

- [ ] **Step 4: Run all verification commands**

```powershell
pytest -q
python skill-package/product-video-pipeline/scripts/self_test.py
git diff --check
```

Expected: all pytest tests pass; self-test prints `product-video-pipeline 自检通过（未联网、未产生费用）`; `git diff --check` emits no errors.

- [ ] **Step 5: Commit final verification changes**

```powershell
git add -- skill-package/product-video-pipeline/scripts/self_test.py tests/test_portable_skill_package.py
git commit -m "test: verify API-first onboarding package"
```
