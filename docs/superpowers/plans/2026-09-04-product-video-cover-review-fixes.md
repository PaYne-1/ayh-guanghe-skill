# Product Video Cover and Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GPT generate complete covers with their titles, require explicit user permission before any paid video rerun, and promote approved videos under the cleaned publish title.

**Architecture:** Keep `视频.mp4` as the stable approval-event identity, but resolve its physical root filename dynamically from `标题.txt`. Teach promotion, validation, audit, organization, and review preview code to use that mapping. Encode the cover and rerun rules in the skill entrypoint and focused references, then synchronize the repository package to the installed skill before repairing the current batch.

**Tech Stack:** Python 3 standard library, Markdown Agent Skills, existing `workflow_cli.py`, built-in GPT image generation, Pillow only for deterministic size normalization without text rendering.

## Global Constraints

- GPT generates the complete cover and exact title in one image-generation request.
- No script, Pillow, ImageMagick, Canvas, or `render_cover.py` may add or repair cover text.
- Automatic review is evidence only; no V02 paid rerun without explicit user authorization after feedback.
- The user's explicit pass decision overrides an automatic failure while preserving all earlier evidence.
- Root video files use the cleaned publish title and retain the approved candidate SHA-256.
- Do not delete historical candidates, failed events, reports, or API responses.
- Do not submit another paid AutoDL task for the current batch.

---

### Task 1: Add failing regression tests for title-based video delivery

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/self_test.py`
- Test: `skill-package/product-video-pipeline/scripts/self_test.py`

**Interfaces:**
- Consumes: `record_artifact_decision`, `promote_approved_artifact`, `validated_promoted_artifact_path`, `audit_promoted_outputs`.
- Produces: executable expectations for title-based `.mp4` promotion and audit.

- [ ] **Step 1: Write the failing test**

Create a temporary valid item, approve `标题.txt`, approve a video candidate as logical artifact `视频.mp4`, and assert:

```python
promoted = workflow_module.promote_approved_artifact(item_dir, video_event)
assert promoted.name == "菜市场湿滑路面 走得稳.mp4"
assert not (item_dir / "视频.mp4").exists()
assert workflow_module.validated_promoted_artifact_path(item_dir, "视频.mp4") == promoted
audit = workflow_module.audit_promoted_outputs(item_dir)
assert any(row["artifact_name"] == "视频.mp4" for row in audit["valid"])
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python skill-package/product-video-pipeline/scripts/self_test.py`

Expected: FAIL because current promotion writes the fixed path `视频.mp4`.

### Task 2: Implement title-based video path resolution

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/workflow_cli.py`
- Test: `skill-package/product-video-pipeline/scripts/self_test.py`

**Interfaces:**
- Produces: `deliverable_root_path(item_dir: Path, artifact_name: str) -> Path`.
- Produces: `clean_publish_title(value: str) -> str` used only for the logical artifact `视频.mp4`.

- [ ] **Step 1: Add minimal filename cleaning and path mapping**

```python
def clean_publish_title(value: str) -> str:
    title = re.sub(r"^\s*(?:发布标题|标题)\s*[:：]\s*", "", value).strip()
    title = re.sub(r"[^\w\u4e00-\u9fff]+", " ", title, flags=re.UNICODE)
    return re.sub(r"\s+", " ", title).strip()

def deliverable_root_path(item_dir: Path, artifact_name: str) -> Path:
    if artifact_name != "视频.mp4":
        return item_dir / artifact_name
    title_path = item_dir / "标题.txt"
    title = clean_publish_title(title_path.read_text(encoding="utf-8-sig"))
    if not title:
        raise ValueError("标题为空，不能生成正式视频文件名")
    return item_dir / f"{title}.mp4"
```

- [ ] **Step 2: Route promotion, validation, audit, organization, and review preview through the mapping**

Replace direct `item_dir / artifact_name` lookup for logical `视频.mp4` with `deliverable_root_path`. Treat only that resolved title-based MP4 as a valid root deliverable; archive unrelated root MP4 files.

- [ ] **Step 3: Run tests and verify GREEN**

Run: `python skill-package/product-video-pipeline/scripts/self_test.py`

Expected: PASS with zero failures.

### Task 3: Add failing rule-contract checks

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/self_test.py`

**Interfaces:**
- Consumes: Markdown files as UTF-8 text.
- Produces: regression checks for complete-cover generation and rerun authorization.

- [ ] **Step 1: Add required phrases**

Assert maintained documents contain the following binding concepts:

```python
"GPT 一次生成包含准确标题的完整封面"
"禁止代码叠字"
"自动验收只形成证据"
"用户明确同意重跑后"
```

- [ ] **Step 2: Add forbidden phrases**

Assert maintained documents no longer contain:

```python
"封面底图不得让生图模型绘制最终中文标题"
"用程序绘制"
"确定性修正中文"
```

- [ ] **Step 3: Run tests and verify RED**

Run: `python skill-package/product-video-pipeline/scripts/self_test.py`

Expected: FAIL because the old cover wording remains and the explicit rerun gate is absent.

### Task 4: Update the product-video skill rules

**Files:**
- Modify: `skill-package/product-video-pipeline/SKILL.md`
- Modify: `skill-package/product-video-pipeline/references/image-generation-routing.md`
- Modify: `skill-package/product-video-pipeline/references/workflow.md`
- Modify: `skill-package/product-video-pipeline/references/delivery-contract.md`
- Modify: `skill-package/product-video-pipeline/references/review-learning.md`
- Mirror the same files to: `C:/Users/Administrator/.agents/skills/product-video-pipeline/`

**Interfaces:**
- Produces: one unambiguous cover recipe and one observable user-authorization gate for reruns.

- [ ] **Step 1: Replace cover-bottom-image language**

Specify that the cover request package includes exact title text and produces one complete cover. Remove all fallback guidance that permits code-rendered text.

- [ ] **Step 2: Make the rerun gate explicit**

Specify the sequence: download → automatic evidence → show candidate and feedback → ask whether to rerun → only explicit yes permits `start-rerun` and paid submission.

- [ ] **Step 3: Preserve user-final-decision semantics**

State that explicit “合格/通过/作为最终视频” creates the latest passed event for that exact candidate, while earlier automatic evidence remains immutable.

- [ ] **Step 4: Run tests and validators**

Run:

```powershell
python skill-package/product-video-pipeline/scripts/self_test.py
python C:/Users/Administrator/.codex/skills/.system/skill-creator/scripts/quick_validate.py skill-package/product-video-pipeline
```

Expected: both exit 0.

### Task 5: Repair the current approved video delivery

**Files:**
- Read: `Y:/0-AI训练/光合视频/轻便侠218 产品图片/生成视频/20260902_批次002/V001_防滑稳定安全_待生成/_工作文件/历史版本/验收候选/视频/20260903T091321785597+0800_d4d27819414c_8c5e5e23-9400-4a79-b45d-ffbed1208cd2.mp4`
- Modify through CLI: current item approval log and title-based root MP4.

**Interfaces:**
- Consumes: user approval in this conversation and the immutable V02 snapshot SHA-256.
- Produces: `菜市场湿滑路面这款电动轮椅依然走得稳.mp4` with the same hash.

- [ ] **Step 1: Record the explicit passed event**

Run `review-output` using the exact V02 snapshot, logical artifact `视频.mp4`, decision `passed`, and feedback quoting the user's “最终的合格视频” decision.

- [ ] **Step 2: Audit the item**

Run `audit-outputs --item-dir ...` and verify the logical `视频.mp4` is reported valid at its title-based physical path.

- [ ] **Step 3: Verify bytes and media**

Run SHA-256, `ffprobe`, and full `ffmpeg -v error -f null -` decode. Expected hash: `d4d27819414cb6eea1aaf13ce50f9d0be848f945807280bcccbda346c7f28391`.

### Task 6: Regenerate the current complete cover with GPT

**Files:**
- Read: current `分镜图.png`, `封面标题.txt`, product references, and selected cover-style reference.
- Create: `_工作文件/生成过程/封面候选_GPT完整含字.png`
- Promote: `封面图.png` through `review-output` after technical and visual checks under the current automatic-mode authorization.

**Interfaces:**
- Consumes: exact title `湿地稳稳走` and image references.
- Produces: one GPT-generated 2160×3840 complete cover containing that exact title.

- [ ] **Step 1: Generate one complete cover**

Use the built-in image-generation tool with the storyboard as product/people reference and the chosen cover image as style reference. The prompt must quote `湿地稳稳走` verbatim and forbid all other text.

- [ ] **Step 2: Inspect the generated original**

Verify visible exact text, product structure, two separate footrests, people count, wet-market setting, and absence of extra text/watermarks.

- [ ] **Step 3: Normalize size without adding text**

If required, use only proportional resize/padding to reach 2160×3840. Do not crop subjects and do not render or alter text.

- [ ] **Step 4: Promote and verify**

Record the new cover passed event, retain the old cover in history, verify final dimensions and SHA-256, and render the final cover in chat.

### Task 7: Final verification

**Files:**
- Verify all modified skill files, tests, installed mirror, and current batch outputs.

- [ ] **Step 1: Compare repository and installed skill copies**

Expected: all modified files have identical SHA-256 hashes.

- [ ] **Step 2: Run full verification**

Run self-test, quick validation, batch output audit, JSON parsing, video decode, image decode/dimensions, and root-directory allowlist checks.

- [ ] **Step 3: Report deliverables**

Show the regenerated cover and playable video, list their absolute paths, and state that no new AutoDL task was submitted.
