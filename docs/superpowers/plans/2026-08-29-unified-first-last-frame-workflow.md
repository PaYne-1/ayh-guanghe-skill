# Unified First/Last Frame Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every new product-video task use one accepted storyboard as the first frame, one independently generated reasonable tail frame, and the MiniMax H3 first/last-frame video workflow.

**Architecture:** Treat the first/last-frame structure as a package-wide invariant rather than a conditional scene mode. Enforce the invariant at the AutoDL client boundary, document the same contract in every routed reference, and mirror the verified portable package into the installed cross-agent skill directory.

**Tech Stack:** Markdown Agent Skills, Python 3 standard library, PowerShell verification, Git.

## Global Constraints

- Every item is a wheelchair-moving two-person dialogue scene.
- The accepted `2160×3840`, `9:16` storyboard is `first_frame` and the independent same-size reasonable tail frame is `last_frame`.
- New videos use `minimax_h3_lightx2v`; `minimax_h3_image_audio_to_video_v2_15s` is not an allowed new-task route.
- The tail frame stays under `_工作文件/生成过程` with path, SHA-256, and structural-check evidence; it is not a second root-level storyboard deliverable.
- Paid submission remains gated by current price, budget, payload dry-run, and explicit authorization.
- Existing unrelated working-tree files must not be staged or modified.

---

### Task 1: Add failing package invariants

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/self_test.py`
- Test: `skill-package/product-video-pipeline/scripts/self_test.py`

**Interfaces:**
- Consumes: portable skill root from `SKILL_ROOT` and `autodl_h3.py submit --dry-run`.
- Produces: a no-network regression check that rejects legacy payloads and detects conditional/default wording in maintained documents.

- [ ] **Step 1: Add the documentation-invariant assertions**

Add a `required_phrases` mapping for `SKILL.md`, `references/workflow.md`, `references/startup-checklist.md`, `references/autodl-h3.md`, and `references/content-contract.md`. Assert that each named file includes the required phrases relevant to its role, including `minimax_h3_lightx2v`, `first_frame`, `last_frame`, `合理尾帧`, or their exact Chinese execution-contract equivalents. Add a `forbidden_phrases` tuple containing:

```python
forbidden_phrases = (
    "其他场景继续使用已确认的现有工作流",
    "是否命中行驶双人对话合理尾帧模式：是 / 否",
    "合理尾帧首尾帧视频预计费用（命中时）",
    "新视频默认使用 `minimax_h3_image_audio_to_video_v2_15s`",
)
```

Read the maintained Markdown files as UTF-8 and assert none contains a forbidden phrase.

- [ ] **Step 2: Replace the old successful dry-run fixture with a first/last-frame fixture**

Use this payload shape:

```python
{
    "prompt": "一镜到底，连续平稳运镜，完整双人对话口播",
    "duration": 15,
    "resolution": "768p竖",
    "first_frame": "data:image/png;base64,AAAA",
    "last_frame": "data:image/png;base64,BBBB",
}
```

Keep the assertions for no network, no charge, `minimax_h3_lightx2v_v5_15s`, resolution preservation, and no legacy watermark field.

- [ ] **Step 3: Add a legacy-route rejection check**

Create a second payload containing only `ref_image_0` and run:

```powershell
python skill-package/product-video-pipeline/scripts/autodl_h3.py submit --payload <legacy-payload.json> --dry-run
```

Assert exit code `2` and stderr contains `first_frame` and `last_frame`.

- [ ] **Step 4: Run the test and verify RED**

Run:

```powershell
python skill-package/product-video-pipeline/scripts/self_test.py
```

Expected: FAIL because the current documents still advertise the legacy default and the current client accepts a payload without `first_frame`/`last_frame`.

- [ ] **Step 5: Commit the failing regression test**

```powershell
git add -- skill-package/product-video-pipeline/scripts/self_test.py
git commit -m "test: require unified first-last-frame workflow"
```

### Task 2: Enforce the fixed AutoDL route

**Files:**
- Modify: `skill-package/product-video-pipeline/scripts/autodl_h3.py`
- Test: `skill-package/product-video-pipeline/scripts/self_test.py`

**Interfaces:**
- Consumes: a JSON payload with `prompt`, `duration`, `resolution`, `first_frame`, and `last_frame`.
- Produces: `submit_payload(...) -> Dict[str, object]` that accepts only the fixed first/last-frame workflow for new submissions.

- [ ] **Step 1: Narrow the supported workflow IDs**

Set:

```python
WORKFLOW_ID = "minimax_h3_lightx2v_v5_15s"
KNOWN_WORKFLOW_IDS = (WORKFLOW_ID, "minimax_h3_lightx2v")
```

This removes the image-plus-audio workflow from the CLI choices and submission API.

- [ ] **Step 2: Add payload validation before preview or network access**

Add a helper that requires the fixed fields, checks `duration == 15`, rejects identical first and last frame values, and requires the prompt to contain all three full-duration constraints:

```python
def validate_first_last_payload(payload: Dict[str, object]) -> None:
    required = ("prompt", "duration", "resolution", "first_frame", "last_frame")
    missing = [field for field in required if not payload.get(field)]
    if missing:
        raise ValueError("首尾帧 payload 缺少字段：" + ", ".join(missing))
    if payload["duration"] != 15:
        raise ValueError("首尾帧视频 duration 必须为 15")
    if payload["first_frame"] == payload["last_frame"]:
        raise ValueError("last_frame 必须独立生成，不得复用 first_frame")
    prompt = str(payload["prompt"])
    required_rules = ("一镜到底", "连续平稳运镜", "完整双人对话口播")
    missing_rules = [rule for rule in required_rules if rule not in prompt]
    if missing_rules:
        raise ValueError("prompt 缺少全程规则：" + ", ".join(missing_rules))
```

Call it from `submit_payload` immediately after confirming the JSON object and workflow ID.

- [ ] **Step 3: Run the focused self-test and verify the client behavior is GREEN**

Run:

```powershell
python skill-package/product-video-pipeline/scripts/self_test.py
```

Expected: it advances past the legacy-payload rejection and then fails only on unchanged documentation invariants.

- [ ] **Step 4: Commit the client enforcement**

```powershell
git add -- skill-package/product-video-pipeline/scripts/autodl_h3.py
git commit -m "feat: enforce first-last-frame submissions"
```

### Task 3: Make all skill instructions consistent

**Files:**
- Modify: `skill-package/product-video-pipeline/SKILL.md`
- Modify: `skill-package/product-video-pipeline/references/workflow.md`
- Modify: `skill-package/product-video-pipeline/references/startup-checklist.md`
- Modify: `skill-package/product-video-pipeline/references/autodl-h3.md`
- Modify: `skill-package/product-video-pipeline/references/content-contract.md`
- Modify: `skill-package/product-video-pipeline/references/ayh-wheelchair-rules.md`
- Modify: `skill-package/product-video-pipeline/references/review-learning.md`
- Modify: `skill-package/product-video-pipeline/references/image-generation-routing.md`
- Test: `skill-package/product-video-pipeline/scripts/self_test.py`

**Interfaces:**
- Consumes: the fixed execution contract and validated AutoDL client from Task 2.
- Produces: one unambiguous workflow understood the same way by Codex, browser-capable agents, and API-capable agents.

- [ ] **Step 1: Rewrite the entrypoint contract**

In `SKILL.md`, replace the independent-audio default and conditional first/last-frame bullets with a positive recipe: every item is a moving elder-plus-companion dialogue, creates one accepted storyboard first frame plus one independent reasonable tail frame, and submits through `minimax_h3_lightx2v`. Preserve the one-storyboard deliverable rule and explicitly place the tail-frame asset under `_工作文件/生成过程`.

- [ ] **Step 2: Rewrite the detailed node flow**

In `references/workflow.md`, make the tail-frame generation mandatory after storyboard acceptance. Remove the normal image-plus-audio branch. Keep the 1–1.5 metre motion progression, product-structure checks, 0–15 second one-shot/stable-camera/complete-dialogue constraints, and failure isolation.

- [ ] **Step 3: Make startup confirmation fixed rather than conditional**

In `references/startup-checklist.md`, replace `是 / 否` with `固定启用`; require first-frame hash, tail-frame hash and structural result, fixed workflow ID, and unconditional first/last-frame cost. Describe native model dialogue as the fixed audio behavior when the selected first/last-frame endpoint has no reference-audio input.

- [ ] **Step 4: Rewrite the AutoDL reference around one default**

In `references/autodl-h3.md`, make `minimax_h3_lightx2v_v5_15s` the default endpoint, document exactly the validated payload fields, and update dry-run and paid-submit examples to that workflow. Remove the default multi-image/multi-audio section; retain only a clearly labelled historical-record note if needed for existing task evidence.

- [ ] **Step 5: Propagate content, product, generation, and review invariants**

Update the remaining four references so every content plan has exactly two distinguishable speakers, every storyboard and tail-frame generation follows the configured image-generation route, both frames preserve the wheelchair structure, and every completed video is checked across the full 15 seconds rather than only at endpoints.

- [ ] **Step 6: Run the package self-test and verify GREEN**

Run:

```powershell
python skill-package/product-video-pipeline/scripts/self_test.py
```

Expected: `product-video-pipeline 自检通过（未联网、未产生费用）`.

- [ ] **Step 7: Commit the instruction update**

```powershell
git add -- skill-package/product-video-pipeline/SKILL.md skill-package/product-video-pipeline/references
git commit -m "docs: unify product videos on first-last-frame flow"
```

### Task 4: Validate and synchronize the installed skill

**Files:**
- Modify: `C:/Users/Administrator/.agents/skills/product-video-pipeline/` by copying the verified portable package contents.
- Test: portable and installed `scripts/self_test.py`.

**Interfaces:**
- Consumes: verified files under `skill-package/product-video-pipeline`.
- Produces: identical installed behavior for other agents reading `C:/Users/Administrator/.agents/skills/product-video-pipeline`.

- [ ] **Step 1: Run the official skill validator on the portable package**

Run:

```powershell
python C:/Users/Administrator/.codex/skills/.system/skill-creator/scripts/quick_validate.py skill-package/product-video-pipeline
```

Expected: validation success with no invalid frontmatter or scaffold placeholders.

- [ ] **Step 2: Synchronize only the skill package**

Copy the contents of `skill-package/product-video-pipeline` into `C:/Users/Administrator/.agents/skills/product-video-pipeline`, preserving the directory structure. Do not copy repository docs or unrelated workspace files.

- [ ] **Step 3: Run installed-package self-test**

Run:

```powershell
python C:/Users/Administrator/.agents/skills/product-video-pipeline/scripts/self_test.py
```

Expected: `product-video-pipeline 自检通过（未联网、未产生费用）`.

- [ ] **Step 4: Compare controlled files**

Use SHA-256 hashes for `SKILL.md`, all files under `references`, and both changed scripts. Expected: no path has a mismatched hash between the portable and installed packages.

- [ ] **Step 5: Run final repository checks**

Run:

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; unrelated pre-existing untracked files remain untouched.

- [ ] **Step 6: Commit the completed portable-package change if any tracked edits remain**

```powershell
git add -- skill-package/product-video-pipeline
git commit -m "chore: finalize unified first-last-frame skill"
```

