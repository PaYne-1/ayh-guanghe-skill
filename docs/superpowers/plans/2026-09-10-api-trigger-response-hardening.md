# API Trigger Response Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every case variant of `配置API` produce a deterministic, status-backed API configuration reply with exactly three correct, unranked categories.

**Architecture:** Keep `api_config.py` as the single source of truth for persistent configuration status and add a read-only `prompt` formatter/CLI command. Tighten the skill routing documents so hosts must invoke that command instead of inventing API categories, then release and deploy the verified package as version `1.8.2`.

**Tech Stack:** Python 3 standard library, Windows HKCU environment variables, Markdown Agent Skill files, pytest, Git archive.

## Global Constraints

- Match `配置api` case-insensitively for the Latin `api` suffix.
- The first reply is backed by `python scripts/api_config.py prompt`; it never scans product folders, creates batches, accesses the network, runs dry-run, generates media, or invokes paid operations.
- The only categories are AutoDL.Art video API, third-party image API, and third-party text API.
- Codex and ChatGPT web image generation use login sessions; MiniMax-H3 is carried by AutoDL.Art and is not a separate configuration category.
- No default, recommendation, or preselected category.
- Full API keys remain hidden and only masked suffixes may appear.

---

### Task 1: Deterministic read-only configuration prompt

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/api_config.py`
- Create: `tests/test_api_configuration_prompt.py`

**Interfaces:**
- Consumes: `status_payload(store=None) -> dict[str, object]` and `format_status(payload) -> str`.
- Produces: `format_configuration_prompt(payload: Mapping[str, object]) -> str` and CLI command `prompt`.

- [ ] **Step 1: Write failing prompt tests**

Create tests that use `MemoryStore` and assert the formatter contains exactly these labels: `AutoDL.Art 视频 API`, `第三方生图 API`, `第三方文本生成 API`. Assert it contains the real masked status, the session/AutoDL clarification, and none of `Recommended`, `GPT Image API`, `配置 MiniMax API`. Add a store whose `get()` raises `OSError("secret-canary")` and assert the CLI failure text is `无法读取当前配置状态，永久配置未更改` without the canary.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:PYTHONUTF8='1'
python -m pytest -q -p no:cacheprovider tests/test_api_configuration_prompt.py
```

Expected: failure because `format_configuration_prompt` and the `prompt` subcommand do not exist.

- [ ] **Step 3: Implement the formatter and command**

Add a formatter shaped as:

```python
def format_configuration_prompt(payload: Mapping[str, object]) -> str:
    status = format_status(payload)
    return (
        "当前 API 配置状态：\n\n"
        f"{status}\n\n"
        "本机 Codex 和 ChatGPT 网页端使用登录状态，不需要配置 API；"
        "MiniMax-H3 视频统一通过 AutoDL.Art。\n\n"
        "请选择本次需要配置或更换的一项：\n"
        "AutoDL.Art 视频 API / 第三方生图 API / 第三方文本生成 API"
    )
```

Register `prompt = subparsers.add_parser("prompt", help="输出固定 API 配置首轮回复")`. In `main`, load `status_payload(store)` and print the formatter. If status loading fails while `args.command == "prompt"`, write only `无法读取当前配置状态，永久配置未更改` to stderr and return `1`.

- [ ] **Step 4: Verify GREEN**

Run the Task 1 pytest command and:

```powershell
python skill-package/product-video-pipeline/scripts/api_config.py prompt
```

Expected: tests pass; live output has three categories and only masked secrets.

- [ ] **Step 5: Commit**

```powershell
git add skill-package/product-video-pipeline/scripts/api_config.py tests/test_api_configuration_prompt.py
git commit -m "fix: make API configuration prompt deterministic"
```

### Task 2: Case-insensitive trigger and mandatory reply contract

**Files:**
- Modify: `skill-package/product-video-pipeline/SKILL.md`
- Modify: `skill-package/product-video-pipeline/references/api-configuration.md`
- Modify: `skill-package/product-video-pipeline/scripts/self_test.py`

**Interfaces:**
- Consumes: Task 1 CLI `python scripts/api_config.py prompt`.
- Produces: a host-facing routing contract covering `配置api`, `配置API`, `配置Api`, and `配置aPi`.

- [ ] **Step 1: Add failing contract assertions**

In `self_test.py`, assert that `SKILL.md` contains all four trigger examples, the phrase `不区分大小写`, and the exact command `python scripts/api_config.py prompt`. Assert `SKILL.md` plus `api-configuration.md` contain the three valid categories and reject the bad screenshot phrases by checking they do not occur outside a clearly marked forbidden-example block.

- [ ] **Step 2: Verify RED**

```powershell
$env:PYTHONUTF8='1'
python skill-package/product-video-pipeline/scripts/self_test.py
```

Expected: failure because the current route only names lowercase `配置api` and does not mandate the prompt command.

- [ ] **Step 3: Tighten routing documentation**

Update the frontmatter description and API routing section to say the Latin suffix is case-insensitive. Require the host to execute `python scripts/api_config.py prompt` before asking for a category. Define the only valid category line as:

```text
AutoDL.Art 视频 API / 第三方生图 API / 第三方文本生成 API
```

State that a failed command produces an explicit read failure and stops; the host may not infer `未配置`. State structurally that the first reply has no recommended/default/preselected option.

- [ ] **Step 4: Verify GREEN**

Run the self-test and Task 1 tests. Expected: both pass without network or charges.

- [ ] **Step 5: Commit**

```powershell
git add skill-package/product-video-pipeline/SKILL.md skill-package/product-video-pipeline/references/api-configuration.md skill-package/product-video-pipeline/scripts/self_test.py
git commit -m "fix: harden API configuration trigger contract"
```

### Task 3: Release, deploy, and verify version 1.8.2

**Files:**
- Modify: `skill-package/product-video-pipeline/VERSION`
- Create: `release/product-video-pipeline-v1.8.2.zip`
- Modify: tests that assert the current package version/archive
- Deploy: `C:/Users/Administrator/.agents/skills/product-video-pipeline`

**Interfaces:**
- Consumes: the fully tested repository skill tree from Tasks 1–2.
- Produces: source package, release archive, and installed runtime with identical critical files.

- [ ] **Step 1: Update release assertions to 1.8.2 and verify RED**

Change current-version/archive assertions from `1.8.1` to `1.8.2`, then run the affected release tests. Expected: failure because `VERSION` and the archive are still `1.8.1`.

- [ ] **Step 2: Set version and build archive**

Set `VERSION` to `1.8.2`. Commit source changes, then build from the committed tree:

```powershell
git archive --format=zip --prefix=product-video-pipeline/ -o release/product-video-pipeline-v1.8.2.zip HEAD:skill-package/product-video-pipeline
```

The archive must exclude `__pycache__`, `.pyc`, `.env`, and plaintext secrets.

- [ ] **Step 3: Run repository verification**

```powershell
$env:PYTHONUTF8='1'
python skill-package/product-video-pipeline/scripts/self_test.py
python -m py_compile skill-package/product-video-pipeline/scripts/api_config.py skill-package/product-video-pipeline/scripts/self_test.py
python C:/Users/Administrator/.codex/skills/.system/skill-creator/scripts/quick_validate.py skill-package/product-video-pipeline
python -m pytest -q -p no:cacheprovider
```

Expected: all commands pass.

- [ ] **Step 4: Deploy installed runtime safely**

Copy the verified `skill-package/product-video-pipeline` tree over `C:/Users/Administrator/.agents/skills/product-video-pipeline` without copying repository-only tests or secrets. Preserve only runtime data files explicitly excluded by the skill package. Verify critical file SHA-256 equality for `SKILL.md`, `VERSION`, `references/api-configuration.md`, `scripts/api_config.py`, and `scripts/self_test.py`.

- [ ] **Step 5: Verify installed prompt**

```powershell
$env:PYTHONUTF8='1'
python C:/Users/Administrator/.agents/skills/product-video-pipeline/scripts/self_test.py
python C:/Users/Administrator/.agents/skills/product-video-pipeline/scripts/api_config.py prompt
```

Expected: self-test passes and the prompt shows three accurate, unranked categories with real masked status.

- [ ] **Step 6: Commit and push**

```powershell
git add skill-package/product-video-pipeline/VERSION release/product-video-pipeline-v1.8.2.zip tests
git commit -m "release: package API prompt hardening v1.8.2"
git push origin HEAD:main
```
