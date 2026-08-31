# Startup Communication Checklist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every `product-video-pipeline` task begin with a complete user-facing requirements/configuration checklist and an explicit reply template before any scanning, initialization, generation, or paid action.

**Architecture:** Express the interaction contract in `SKILL.md` and keep its complete reusable template in `references/startup-checklist.md`. Protect the behavior with repository tests and portable self-test phrase assertions, then synchronize the installed skill and publish a v1.6.1 archive containing exactly the tracked package files.

**Tech Stack:** Agent Skills Markdown, Python 3.9+, pytest, PowerShell ZIP packaging.

## Global Constraints

- Every task starts with the complete three-section communication checklist.
- The three sections are exactly `你需要提供的内容`, `本次配置明细`, and `请你回复`.
- Known values remain visible; missing values use `待确认` or `需要提供`.
- Before the user's explicit reply, do not scan product files, initialize a batch, generate images, query paid services, or submit video jobs.
- API keys are never requested in chat; only secure environment-variable connection status is requested.
- Dry-run is offline and free, and never grants paid authorization.
- Version becomes `1.6.1`; installed source and release ZIP must match the portable package.

---

### Task 1: Add failing startup-contract tests

**Files:**
- Modify: `tests/test_portable_skill_package.py`
- Modify: `skill-package/product-video-pipeline/scripts/self_test.py`

**Interfaces:**
- Consumes: UTF-8 text from `SKILL.md` and `references/startup-checklist.md`.
- Produces: assertions for the three headings, always-on behavior, pre-reply prohibitions, and reply-template wording.

- [ ] **Step 1: Add the repository test**

Add a test that reads both files and asserts the startup reference contains `你需要提供的内容`, `本次配置明细`, `请你回复`, `每次任务`, `未收到用户明确回复前`, `不扫描产品素材`, and `可复制填写`; assert `SKILL.md` says the checklist is the first action on every task.

- [ ] **Step 2: Extend portable self-test requirements**

Add the same invariant phrases to the existing `required_phrases` mapping in `scripts/self_test.py` so extracted and installed copies validate themselves.

- [ ] **Step 3: Verify RED**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "startup_communication" -q
python skill-package/product-video-pipeline/scripts/self_test.py
```

Expected: the focused pytest and self-test fail because the new headings and pre-reply contract are absent.

- [ ] **Step 4: Commit failing tests**

```powershell
git add -- tests/test_portable_skill_package.py skill-package/product-video-pipeline/scripts/self_test.py
git commit -m "test: require complete startup communication"
```

### Task 2: Implement the complete first-response contract

**Files:**
- Modify: `skill-package/product-video-pipeline/SKILL.md`
- Modify: `skill-package/product-video-pipeline/references/startup-checklist.md`

**Interfaces:**
- Consumes: task facts already present in conversation without scanning or external calls.
- Produces: a three-section first response and a single copyable reply template.

- [ ] **Step 1: Update required routing**

Make the first required action on every task: read the startup checklist and show all three sections. State that known configuration never suppresses the checklist and that execution waits for an explicit reply.

- [ ] **Step 2: Add the fixed user-facing template**

In `startup-checklist.md`, define fields and statuses for product path/name, selling points, count, cover references, API/channel status, mode, models, image route, storyboard/video resolution, duration, ratio, workflow, audio, watermark, concurrency, retries, live price, budget, output, and rules library. End with a copyable reply form containing only user-controlled or missing values.

- [ ] **Step 3: Preserve the post-reply final confirmation**

Keep the existing detailed execution confirmation. Clarify that after the user replies, the agent may verify configuration, scan only the product folder first level, query current prices, and generate `启动确认单.json`; paid submission remains separately authorized.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "startup_communication" -q
python skill-package/product-video-pipeline/scripts/self_test.py
```

Expected: PASS.

- [ ] **Step 5: Commit the contract**

```powershell
git add -- skill-package/product-video-pipeline/SKILL.md skill-package/product-video-pipeline/references/startup-checklist.md
git commit -m "feat: require complete startup communication"
```

### Task 3: Version and publish v1.6.1

**Files:**
- Modify: `skill-package/product-video-pipeline/VERSION`
- Modify: `tests/test_portable_skill_package.py`
- Create: `release/product-video-pipeline-v1.6.1.zip`
- Modify: `C:/Users/Administrator/.agents/skills/product-video-pipeline/**` by tracked-file synchronization

**Interfaces:**
- Consumes: all tracked files under `skill-package/product-video-pipeline`.
- Produces: installed v1.6.1 and a portable archive whose contents match source by SHA-256.

- [ ] **Step 1: Add the failing release assertions**

Change current-package version assertions to `1.6.1` and add a ZIP test for `product-video-pipeline-v1.6.1.zip`. It must verify top-level `product-video-pipeline/`, `VERSION=1.6.1`, the three checklist headings, and exclusion of `.env`, `__pycache__`, and `.pyc`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/test_portable_skill_package.py -k "v1_6_1" -q
```

Expected: FAIL because the version and archive are not yet v1.6.1.

- [ ] **Step 3: Set package version and build archive**

Set `VERSION` to `1.6.1`. Stage only tracked skill files into an isolated temporary directory with top-level folder `product-video-pipeline`, then use `Compress-Archive` to create `release/product-video-pipeline-v1.6.1.zip`.

- [ ] **Step 4: Synchronize installed skill**

Copy every tracked source package file to `C:/Users/Administrator/.agents/skills/product-video-pipeline` without deleting target-only learning data. Compare SHA-256 for all copied files.

- [ ] **Step 5: Verify archive and installed copy**

Extract the archive into an isolated temporary directory; run both extracted and installed `scripts/self_test.py`. Verify version, required headings, excluded sensitive/cache files, and source/archive/installed hashes.

- [ ] **Step 6: Run full regression suite**

```powershell
python -m pytest tests/test_portable_skill_package.py -q
python skill-package/product-video-pipeline/scripts/self_test.py
python C:/Users/Administrator/.agents/skills/product-video-pipeline/scripts/self_test.py
```

Expected: all tests pass with no tracebacks.

- [ ] **Step 7: Commit release**

```powershell
git add -- skill-package/product-video-pipeline/VERSION tests/test_portable_skill_package.py release/product-video-pipeline-v1.6.1.zip
git commit -m "release: package product video skill v1.6.1"
```

### Task 4: Demonstrate the new task-start interaction

**Files:**
- No repository changes.

**Interfaces:**
- Consumes: the current 爱优护 sample-video request.
- Produces: one complete three-section checklist with current known values and a copyable reply template.

- [ ] **Step 1: Invoke the installed skill in the current task context**

Use the existing known product and API status without scanning again. Mark the missing cover-reference folder and user-controlled choices explicitly.

- [ ] **Step 2: Confirm behavior against the spec**

Verify all configuration fields are visible, only missing/user-controlled fields appear in the reply template, and no production node starts before the user replies.
