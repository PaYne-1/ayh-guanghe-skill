# Seven Root Deliverables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make publish body, hashtags, first-frame storyboard, and tail-frame storyboard independently saved and approved as part of seven fixed root deliverables.

**Architecture:** Keep the existing candidate → immutable review snapshot → explicit `passed` event → root promotion pipeline. Expand its fixed allowlist from five to seven files, split body/tag candidate creation, promote the checked tail frame as `尾帧图.png`, and express the same contract across instructions, runtime tests, installed skill, and the v1.6.0 release archive.

**Tech Stack:** Python 3 standard library, pytest, Markdown Agent Skills, PowerShell packaging, Git.

## Global Constraints

- Root deliverables are exactly `标题.txt`, `发布正文.txt`, `话题标签.txt`, `分镜图.png`, `尾帧图.png`, `封面图.png`, and `视频.mp4`, plus `_工作文件/`.
- Every root deliverable requires its own latest explicit `passed` event bound to the candidate path and SHA-256.
- `_工作文件/生成过程/发布正文.txt` contains body text only; `_工作文件/生成过程/话题标签.txt` contains all tags separated by spaces.
- `分镜图.png` is `first_frame`; `尾帧图.png` is the separately generated `last_frame`; their SHA-256 values must differ.
- Existing historical batches are not rewritten or given fabricated approvals.
- Version becomes `1.6.0`; the installed package and release ZIP must match the portable source package.
- Existing unrelated untracked workspace files remain untouched.

---

### Task 1: Specify seven independent deliverables with failing tests

**Files:**
- Modify: `tests/test_portable_skill_package.py`
- Modify: `skill-package/product-video-pipeline/scripts/self_test.py`

**Interfaces:**
- Consumes: `workflow_cli.DELIVERABLE_NAMES`, `save_content_package`, `record_artifact_decision`, `promote_approved_artifact`, and `audit_promoted_outputs`.
- Produces: regression tests that define exact filenames, split candidate bytes, independent approvals, and tail-frame promotion.

- [ ] **Step 1: Update the fixed deliverable expectation**

Use this exact set in repository tests:

```python
deliverables = {
    "视频.mp4",
    "封面图.png",
    "发布正文.txt",
    "话题标签.txt",
    "标题.txt",
    "分镜图.png",
    "尾帧图.png",
}
assert runtime.DELIVERABLE_NAMES == deliverables
```

Replace old `发布正文.md` fixtures with `发布正文.txt` and extend organizer/audit assertions from five to seven files.

- [ ] **Step 2: Assert split body and hashtag candidate content**

After `save_content_package(...)`, assert:

```python
process = item / "_工作文件" / "生成过程"
assert (process / "发布正文.txt").read_text(encoding="utf-8") == package["publish_body"] + "\n"
assert (process / "话题标签.txt").read_text(encoding="utf-8") == " ".join(package["hashtags"]) + "\n"
assert not any(tag in (process / "发布正文.txt").read_text(encoding="utf-8") for tag in package["hashtags"])
```

- [ ] **Step 3: Assert independent tail-frame review and promotion**

Create different first/tail candidate bytes, record separate `passed` decisions for `分镜图.png` and `尾帧图.png`, promote both, and assert the root hashes differ. Also assert a tail candidate without a `passed` event is absent from the root after `audit_promoted_outputs`.

- [ ] **Step 4: Add portable self-test invariants**

Assert `DELIVERABLE_NAMES` has seven exact names, split candidate files exist with exact content, and maintained documents contain `尾帧图.png` and `话题标签.txt` while omitting `五项最终产出` and `发布正文.md` as the current format.

- [ ] **Step 5: Run RED**

Run:

```powershell
$env:PYTHONUTF8='1'
python -m pytest tests/test_portable_skill_package.py -q
python skill-package/product-video-pipeline/scripts/self_test.py
```

Expected: FAIL because the current allowlist has five items, body and tags share `发布正文.md`, and `尾帧图.png` cannot be reviewed or promoted.

- [ ] **Step 6: Commit the failing tests**

```powershell
git add -- tests/test_portable_skill_package.py skill-package/product-video-pipeline/scripts/self_test.py
git commit -m "test: require seven independent deliverables"
```

### Task 2: Implement the seven-file runtime contract

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/workflow_cli.py`
- Test: `tests/test_portable_skill_package.py`
- Test: `skill-package/product-video-pipeline/scripts/self_test.py`

**Interfaces:**
- Consumes: structured content JSON with `publish_body` and `hashtags`, plus candidates under `_工作文件`.
- Produces: seven-name allowlist, body/tag candidates, and independent approval/promotion/audit behavior.

- [ ] **Step 1: Expand the allowlist**

Replace the constant with:

```python
DELIVERABLE_NAMES = {
    "视频.mp4",
    "封面图.png",
    "发布正文.txt",
    "话题标签.txt",
    "标题.txt",
    "分镜图.png",
    "尾帧图.png",
}
```

Change the promotion error text to `只有七项固定产出的 passed 事件可以晋升`.

- [ ] **Step 2: Split content candidates**

In `save_content_package`, write:

```python
_write_candidate_preserving_previous(item_dir, "发布正文.txt", f"{package['publish_body']}\n", now)
_write_candidate_preserving_previous(item_dir, "话题标签.txt", " ".join(package["hashtags"]) + "\n", now)
```

Remove the combined `发布正文.md` write.

- [ ] **Step 3: Verify GREEN for runtime tests**

Run:

```powershell
$env:PYTHONUTF8='1'
python -m pytest tests/test_portable_skill_package.py -q
python skill-package/product-video-pipeline/scripts/self_test.py
```

Expected: runtime-focused failures disappear; remaining failures, if any, identify stale documentation/version assertions only.

- [ ] **Step 4: Commit the runtime implementation**

```powershell
git add -- skill-package/product-video-pipeline/scripts/workflow_cli.py
git commit -m "feat: support seven root deliverables"
```

### Task 3: Align all skill instructions and version

**Files:**
- Modify: `skill-package/product-video-pipeline/SKILL.md`
- Modify: `skill-package/product-video-pipeline/references/workflow.md`
- Modify: `skill-package/product-video-pipeline/references/content-contract.md`
- Modify: `skill-package/product-video-pipeline/references/image-generation-routing.md`
- Modify: `skill-package/product-video-pipeline/references/review-learning.md`
- Modify: `skill-package/product-video-pipeline/references/startup-checklist.md`
- Modify: `skill-package/product-video-pipeline/references/autodl-h3.md`
- Modify: `skill-package/product-video-pipeline/VERSION`
- Test: `tests/test_portable_skill_package.py`

**Interfaces:**
- Consumes: the runtime behavior from Task 2.
- Produces: one discoverable, non-contradictory seven-file contract for every agent using the skill.

- [ ] **Step 1: Rewrite the entrypoint and workflow tree**

State the seven exact root filenames, seven separate explicit approvals, body/tag split, and `分镜图.png`/`尾帧图.png` mapping. In the file tree, show both candidates and both root frame files.

- [ ] **Step 2: Rewrite content and image-generation references**

Route `publish_body` to `发布正文.txt`, `hashtags` to `话题标签.txt`, and the accepted tail candidate to root `尾帧图.png`. Require a user `passed` event after tail structural checks and before video submission.

- [ ] **Step 3: Rewrite review, startup, and AutoDL gates**

Require valid promoted paths and matching approval hashes for both `分镜图.png` and `尾帧图.png`; list body and hashtags as separate review nodes. Preserve the rule that technical checks cannot replace user approval.

- [ ] **Step 4: Bump version and version assertions**

Set `VERSION` and fixed test assertions to `1.6.0`.

- [ ] **Step 5: Search for stale current-format language**

Run:

```powershell
rg -n "五项最终产出|只有五项|发布正文\.md|不作为第二张一级分镜|不晋升为第二张一级分镜" skill-package/product-video-pipeline tests/test_portable_skill_package.py
```

Expected: no current-contract occurrence; historical migration wording may remain only when explicitly labelled as legacy.

- [ ] **Step 6: Run all tests and commit**

Run:

```powershell
$env:PYTHONUTF8='1'
python -m pytest tests/test_portable_skill_package.py -q
python skill-package/product-video-pipeline/scripts/self_test.py
```

Expected: all tests pass and self-test reports no network/no charge.

```powershell
git add -- skill-package/product-video-pipeline tests/test_portable_skill_package.py
git commit -m "docs: define seven approved root outputs"
```

### Task 4: Publish and synchronize v1.6.0

**Files:**
- Create: `release/product-video-pipeline-v1.6.0.zip`
- Modify: `tests/test_portable_skill_package.py`
- Modify: `C:/Users/Administrator/.agents/skills/product-video-pipeline/` by non-destructive copy from the verified source package.

**Interfaces:**
- Consumes: tracked portable package files after Task 3.
- Produces: installed v1.6.0 skill and a portable ZIP whose tracked files match source by SHA-256.

- [ ] **Step 1: Add and run the failing release test**

Add a test for `release/product-video-pipeline-v1.6.0.zip` that verifies the top-level `product-video-pipeline/` directory, `VERSION=1.6.0`, seven-file wording, no `.env`, no `__pycache__`, and no `.pyc`. Run that test and verify it fails because the v1.6.0 archive does not exist.

- [ ] **Step 2: Run source validation**

Run:

```powershell
$env:PYTHONUTF8='1'
python C:/Users/Administrator/.codex/skills/.system/skill-creator/scripts/quick_validate.py skill-package/product-video-pipeline
python skill-package/product-video-pipeline/scripts/self_test.py
```

Expected: `Skill is valid!` and the offline self-test passes.

- [ ] **Step 3: Build the ZIP from tracked package files**

Use `git -c core.quotePath=false ls-files 'skill-package/product-video-pipeline/**'` to stage only tracked files under an ignored temporary directory with top-level folder `product-video-pipeline/`, then create `release/product-video-pipeline-v1.6.0.zip`. Do not include `.env`, caches, `.pyc`, product material, or tests.

- [ ] **Step 4: Extract and validate the ZIP**

Expand the ZIP into an ignored verification directory. Run `quick_validate.py` and `scripts/self_test.py` from the extracted package. Compare SHA-256 for every tracked source package file against the extracted file.

- [ ] **Step 5: Synchronize the installed package**

Copy every tracked source package file to `C:/Users/Administrator/.agents/skills/product-video-pipeline` without deleting target-only learning data. Run installed `scripts/self_test.py`, verify installed `VERSION` is `1.6.0`, and compare every copied file by SHA-256.

- [ ] **Step 6: Run final verification**

Run:

```powershell
$env:PYTHONUTF8='1'
python -m pytest tests/test_portable_skill_package.py -q
python skill-package/product-video-pipeline/scripts/self_test.py
python C:/Users/Administrator/.agents/skills/product-video-pipeline/scripts/self_test.py
python C:/Users/Administrator/.codex/skills/.system/skill-creator/scripts/quick_validate.py skill-package/product-video-pipeline
git diff --check
git status --short --branch
```

Expected: all tests pass, both self-tests pass, skill validation passes, no tracked working-tree changes remain after commit, and unrelated untracked files remain untouched.

- [ ] **Step 7: Commit the release artifact and release test**

```powershell
git add -- release/product-video-pipeline-v1.6.0.zip tests/test_portable_skill_package.py
git commit -m "release: package product video skill v1.6.0"
```
