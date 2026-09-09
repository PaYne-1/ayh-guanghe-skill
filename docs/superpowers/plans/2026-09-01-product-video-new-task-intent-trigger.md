# Product Video New-Task Intent Trigger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make any clear natural-language intent to begin a new product-video task trigger the complete startup checklist without requiring a fixed phrase or filled template.

**Architecture:** Keep intent interpretation in the skill documentation and enforce its required contract with the existing offline `self_test.py`. `SKILL.md` defines routing behavior; `references/startup-checklist.md` defines trigger, ambiguity handling, and response shape.

**Tech Stack:** Markdown Agent Skill instructions, Python 3 offline self-test.

## Global Constraints

- Trigger from semantic new-task intent, not exact keywords or a fixed opening phrase.
- Carry already supplied values into the checklist as `已提供`.
- If the message could mean a current-task rerun, ask only whether it is a new task or continuation.
- Before checklist confirmation, do not scan, create a batch, query prices, generate media, dry-run, or call paid APIs.
- A previous one-time automatic-execution authorization never carries into a new task.

---

### Task 1: Add Failing Contract Tests

**Files:**
- Modify: `C:/Users/Administrator/.agents/skills/product-video-pipeline/scripts/self_test.py:352`
- Test: `C:/Users/Administrator/.agents/skills/product-video-pipeline/scripts/self_test.py`

**Interfaces:**
- Consumes: UTF-8 contents of `SKILL.md` and `references/startup-checklist.md`.
- Produces: Offline assertions that fail unless the semantic trigger contract is documented in both files.

- [ ] **Step 1: Extend required phrases before editing production skill documents**

Add these strings to the existing `required_phrases` entries for both `SKILL.md` and `references/startup-checklist.md`:

```python
"自然语言明确表达",
"不依赖固定关键词",
"全新任务还是继续当前任务",
"已提供的信息自动带入",
"单次自动执行授权不得跨任务继承",
```

Add this string to `forbidden_phrases`:

```python
"必须使用固定开头才能启动新任务",
```

- [ ] **Step 2: Run the self-test and verify RED**

Run:

```powershell
python C:\Users\Administrator\.agents\skills\product-video-pipeline\scripts\self_test.py
```

Expected: FAIL on the first missing semantic-trigger phrase in `SKILL.md`; the failure must be due to missing behavior documentation, not syntax or import errors.

- [ ] **Step 3: Commit the failing contract test**

If the installed skill directory is a Git repository, commit only `scripts/self_test.py`. Otherwise preserve the failing test in place and record its hash before implementation.

---

### Task 2: Implement Semantic New-Task Routing

**Files:**
- Modify: `C:/Users/Administrator/.agents/skills/product-video-pipeline/SKILL.md:14`
- Modify: `C:/Users/Administrator/.agents/skills/product-video-pipeline/references/startup-checklist.md:3`
- Test: `C:/Users/Administrator/.agents/skills/product-video-pipeline/scripts/self_test.py`

**Interfaces:**
- Consumes: A user message and the current conversation/task context.
- Produces: Either the complete three-block startup checklist, one ambiguity question, or continuation of the current task.

- [ ] **Step 1: Update the top-level routing rule in `SKILL.md`**

Immediately after Required routing item 0, add this exact behavior:

```markdown
**新任务语义触发**：用户以任何自然语言明确表达要开始新的任务、项目、产品或批次时，立即进入上述启动清单；不依赖固定关键词、固定开头或填写模板。用户同一消息中已提供的信息自动带入清单并标记为 `已提供`，只询问缺失项。若“再来一个、重新生成”等表达无法区分全新任务与当前任务重跑，只问一句“这是开始全新任务还是继续当前任务？”，在用户回答前不执行任何生产动作。上一次任务的单次自动执行授权不得跨任务继承。
```

- [ ] **Step 2: Add the detailed trigger contract to `startup-checklist.md`**

Under `## 每次任务的首次沟通`, before the existing first paragraph, add:

```markdown
### 新任务意图识别

用户不需要使用固定开头或复制模板。只要通过自然语言明确表达要开始新的任务、项目、产品或批次，就发送本文件规定的完整三段式清单；不依赖固定关键词。用户已经在同一条消息中提供的信息自动带入并标记为 `已提供`。

当“再来一个、重新生成、换一版”等表达可能是当前任务重跑，也可能是全新任务时，只问一句：“这是开始全新任务还是继续当前任务？”确认前不得扫描、建批次、查询价格、生图、dry-run 或付费提交。上一次任务的单次自动执行授权不得跨任务继承。
```

- [ ] **Step 3: Add explicit routing examples**

Add this table after the new trigger section:

```markdown
| 用户表达 | 行为 |
|---|---|
| “开始一个新任务” | 立即发送完整启动清单 |
| “换个产品重新做，目录是 X” | 发送清单，并把目录标记为已提供 |
| “再生成一个” | 只确认是全新任务还是继续当前任务 |
| “继续刚才那个” | 继续当前任务，不发送新任务清单 |
```

- [ ] **Step 4: Run the self-test and verify GREEN**

Run:

```powershell
python C:\Users\Administrator\.agents\skills\product-video-pipeline\scripts\self_test.py
```

Expected final line:

```text
product-video-pipeline 自检通过（未联网、未产生费用）
```

Exit code must be `0`.

- [ ] **Step 5: Inspect the exact diff**

Run:

```powershell
git -C C:\Users\Administrator\.agents\skills\product-video-pipeline diff -- SKILL.md references/startup-checklist.md scripts/self_test.py
```

If that directory is not a Git repository, use:

```powershell
Get-FileHash C:\Users\Administrator\.agents\skills\product-video-pipeline\SKILL.md,C:\Users\Administrator\.agents\skills\product-video-pipeline\references\startup-checklist.md,C:\Users\Administrator\.agents\skills\product-video-pipeline\scripts\self_test.py -Algorithm SHA256
```

Confirm no checklist fields, pricing rules, API safety rules, or paid-submission gates were removed.

---

### Task 3: Final Skill Verification and Learning Record

**Files:**
- Verify: `C:/Users/Administrator/.agents/skills/product-video-pipeline/SKILL.md`
- Verify: `C:/Users/Administrator/.agents/skills/product-video-pipeline/references/startup-checklist.md`
- Verify: `C:/Users/Administrator/.agents/skills/product-video-pipeline/scripts/self_test.py`
- Create: `Y:/0-AI训练/光合视频/轻便侠218 产品图片/生成视频/20260831_批次001/V001_防滑安全_待生成/_工作文件/任务状态/新任务语义触发规则验证.json`

**Interfaces:**
- Consumes: The confirmed design spec and self-test output.
- Produces: Auditable verification state for the learning-mode experiment.

- [ ] **Step 1: Run a clean final self-test**

Run the same `self_test.py` command again in a fresh process. Expected: exit `0` and the success line above.

- [ ] **Step 2: Verify required text and absence of the forbidden fixed-phrase rule**

Run:

```powershell
rg -n "自然语言明确表达|不依赖固定关键词|全新任务还是继续当前任务|已提供的信息自动带入|单次自动执行授权不得跨任务继承" C:\Users\Administrator\.agents\skills\product-video-pipeline\SKILL.md C:\Users\Administrator\.agents\skills\product-video-pipeline\references\startup-checklist.md
rg -n "必须使用固定开头才能启动新任务" C:\Users\Administrator\.agents\skills\product-video-pipeline\SKILL.md C:\Users\Administrator\.agents\skills\product-video-pipeline\references\startup-checklist.md
```

Expected: the first command returns matches in both files; the second command returns no matches.

- [ ] **Step 3: Write the verification record**

Create JSON containing:

```json
{
  "status": "passed",
  "behavior": "semantic_new_task_trigger",
  "requires_fixed_phrase": false,
  "ambiguous_message_action": "ask_new_or_continue_once",
  "carries_prior_one_time_authorization": false,
  "self_test_exit_code": 0
}
```

- [ ] **Step 4: Commit installed-skill changes if the skill directory is versioned**

Commit only the three modified skill files and the verification record if they share a repository. Do not add unrelated files.
