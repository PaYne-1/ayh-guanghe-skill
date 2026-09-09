# 全局产品视频任务窗口路由 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每个全新 Codex 任务窗口的第一条用户消息无条件进入产品视频启动清单，同时让已有窗口仅在用户确认切换任务后触发该清单。

**Architecture:** 使用始终加载的全局 `AGENTS.md` 作为首条消息路由入口；`product-video-pipeline` 的发现描述和内部启动规则作为第二层契约；项目内与当前生效副本各自的离线 `self_test.py` 检查同一组窗口路由契约。项目内 `skill-package` 是可提交的技能源码；`SKILL.md` 和启动清单修改完成后以相同文本同步到用户目录中的生效副本，生效副本自检脚本中既有的额外学习测试保持不变。

**Tech Stack:** Markdown 规则文件、Python 3 离线自检、PowerShell、Git

## Global Constraints

- 全新 Codex 任务窗口的第一条用户消息无论内容是什么，都必须先触发 `product-video-pipeline`。
- 启动时必须完整展示 `你需要提供的内容`、`本次配置明细`、`请你回复` 三个区块。
- 第一条消息已有信息自动带入并标记为 `已提供`。
- 已有任务窗口的普通消息继续当前任务；出现新任务意图时只询问一次“是否开始全新的产品视频任务？”。
- 用户确认“是”后才发送完整启动清单；确认“否”则继续当前任务。
- 清单回复或任务切换确认前，不扫描、不创建批次、不查询价格、不生成媒体、不 dry-run、不调用付费接口。
- 上一个任务的单次自动执行、预算和付费授权不得继承。
- 不改变三段式清单字段、11 节点流程、预算规则和付费授权要求。

## File Map

- `C:\Users\Administrator\.codex\AGENTS.md`：始终加载的任务窗口路由主入口。
- `D:\0-AI 项目\ayh-h3\skill-package\product-video-pipeline\SKILL.md`：可移植技能的发现描述与内部路由契约。
- `D:\0-AI 项目\ayh-h3\skill-package\product-video-pipeline\references\startup-checklist.md`：新窗口、旧窗口和三段式清单的具体沟通规则。
- `D:\0-AI 项目\ayh-h3\skill-package\product-video-pipeline\scripts\self_test.py`：可提交的离线路由契约测试。
- `C:\Users\Administrator\.agents\skills\product-video-pipeline\SKILL.md`：当前 Codex 实际读取的技能副本。
- `C:\Users\Administrator\.agents\skills\product-video-pipeline\references\startup-checklist.md`：当前生效的启动清单副本。
- `C:\Users\Administrator\.agents\skills\product-video-pipeline\scripts\self_test.py`：当前生效副本的离线自检入口。

---

### Task 1: 添加全局路由契约的失败测试

**Files:**
- Modify: `D:\0-AI 项目\ayh-h3\skill-package\product-video-pipeline\scripts\self_test.py:352`
- Modify: `C:\Users\Administrator\.agents\skills\product-video-pipeline\scripts\self_test.py:352`

**Interfaces:**
- Consumes: `SKILL_ROOT`、项目内或用户目录内的技能文件，以及 `C:\Users\Administrator\.codex\AGENTS.md`。
- Produces: 对新窗口无条件触发、旧窗口确认触发、三段式清单和授权边界的离线字符串契约。

- [ ] **Step 1: 在可移植自检中加入全局入口定位和契约断言**

在 `skill_text` 读取逻辑前加入全局规则路径，并把原有只检查关键词的发现测试替换为以下断言。路径允许通过 `CODEX_GLOBAL_AGENTS_PATH` 覆盖，便于在临时目录中验证：

```python
    global_agents_path = Path(
        os.environ.get(
            "CODEX_GLOBAL_AGENTS_PATH",
            str(Path.home() / ".codex" / "AGENTS.md"),
        )
    )
    assert global_agents_path.is_file(), f"缺少全局规则文件：{global_agents_path}"
    global_agents_text = global_agents_path.read_text(encoding="utf-8")
    for phrase in (
        "每个全新的 Codex 任务窗口",
        "第一条用户消息无论内容是什么",
        "product-video-pipeline",
        "是否开始全新的产品视频任务？",
        "普通消息继续当前任务",
        "不调用付费接口",
    ):
        assert phrase in global_agents_text, f"全局任务窗口路由缺少契约：{phrase}"

    skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    skill_frontmatter = skill_text.split("---", 2)[1]
    for phrase in (
        "first user message of every new Codex task window",
        "regardless of wording",
        "existing window",
        "开始新任务",
    ):
        assert phrase in skill_frontmatter, f"SKILL.md 发现描述缺少窗口路由：{phrase}"
```

从 `required_phrases["SKILL.md"]` 与 `required_phrases["references/startup-checklist.md"]` 中删除已经失效的旧契约：

```python
            "自然语言明确表达",
            "不依赖固定关键词",
            "全新任务还是继续当前任务",
            "单次自动执行授权不得跨任务继承",
```

再把以下新契约加入这两个元组：

```python
            "全新的 Codex 任务窗口",
            "第一条用户消息无论内容是什么",
            "是否开始全新的产品视频任务？",
            "普通消息继续当前任务",
            "上一个任务",
            "付费授权不得继承",
```

把旧确认话术加入 `forbidden_phrases`，防止新旧规则并存：

```python
        "这是开始全新任务还是继续当前任务？",
```

- [ ] **Step 2: 将相同测试修改应用到当前生效副本**

使用 `apply_patch` 对 `C:\Users\Administrator\.agents\skills\product-video-pipeline\scripts\self_test.py` 应用相同的新增断言、旧短语删除和禁用话术检查；保留生效副本中已经存在的其他学习规则和 AutoDL 自检，不覆盖整个文件，也不要求两个自检脚本的其他部分逐字一致。

- [ ] **Step 3: 运行测试并确认 RED 原因准确**

Run:

```powershell
python "C:\Users\Administrator\.agents\skills\product-video-pipeline\scripts\self_test.py"
```

Expected: 退出码非零，首次失败信息为 `全局任务窗口路由缺少契约：每个全新的 Codex 任务窗口`。不得出现联网请求、任务提交或费用。

- [ ] **Step 4: 提交失败测试**

```powershell
git add -- "skill-package/product-video-pipeline/scripts/self_test.py"
git commit -m "test: require global product video task router"
```

### Task 2: 实现全局入口与技能内部窗口路由

**Files:**
- Modify: `C:\Users\Administrator\.codex\AGENTS.md:3`
- Modify: `D:\0-AI 项目\ayh-h3\skill-package\product-video-pipeline\SKILL.md:1-16`
- Modify: `D:\0-AI 项目\ayh-h3\skill-package\product-video-pipeline\references\startup-checklist.md:3-20`
- Modify: `C:\Users\Administrator\.agents\skills\product-video-pipeline\SKILL.md:1-16`
- Modify: `C:\Users\Administrator\.agents\skills\product-video-pipeline\references\startup-checklist.md:3-20`

**Interfaces:**
- Consumes: Codex 对任务窗口是否已有上下文的判断，以及用户对切换确认问题的“是/否”回答。
- Produces: 新窗口首条消息直接进入清单；旧窗口只有确认后切换；所有生产与付费动作继续受启动授权限制。

- [ ] **Step 1: 在全局规则中加入强制窗口路由**

紧跟 `## 自动发现与调用技能` 的现有段落后加入：

```markdown
### 产品视频任务窗口路由（强制）

- 在每个全新的 Codex 任务窗口中，第一条用户消息无论内容是什么，必须先调用 `product-video-pipeline`，读取其启动确认单，并完整展示“你需要提供的内容”“本次配置明细”“请你回复”三个区块。第一条消息已经提供的信息带入清单并标记为“已提供”。这一步只进入启动沟通，不执行原始请求。
- 在已有任务窗口中，普通消息继续当前任务，不触发产品视频启动清单。只有当用户表达“开始新任务、开始新项目、换个产品、再开一批”或同义意图时，先且只询问一次：“是否开始全新的产品视频任务？”
- 用户确认“是”后，才发送完整三段式启动清单；用户确认“否”则继续当前任务。用户未回答切换确认或未回复启动清单前，不扫描产品目录、不创建批次、不查询价格、不生成媒体、不 dry-run，也不调用付费接口。
- 上一个任务的“本次直接执行”、预算确认、付费授权和临时配置不得继承到新任务；已安全接入的环境变量只能标记为“已接入”，仍须在新任务清单中确认是否继续使用。
```

- [ ] **Step 2: 更新技能发现描述和内部路由**

将 `SKILL.md` 的 frontmatter 描述改为：

```yaml
description: Use on the first user message of every new Codex task window regardless of wording, and in an existing window after the user confirms a new product-video task prompted by 开始新任务、开始新项目、换个产品、再开一批; also use for batch product short-video planning, storyboard and cover generation, AutoDL.Art MiniMax-H3 submission, task polling, MP4 review, or feedback learning, especially for 爱优护、电动轮椅、淘宝/天猫光合视频。
```

用下面的窗口规则替换当前 `**新任务语义触发**` 段落：

```markdown
   **任务窗口路由**：在全新的 Codex 任务窗口中，第一条用户消息无论内容是什么，都立即进入上述启动清单；用户同一消息中已提供的信息自动带入并标记为 `已提供`。在已有任务窗口中，普通消息继续当前任务，不重新发送清单；当用户表达“开始新任务、开始新项目、换个产品、再开一批”或同义意图时，只询问一次“是否开始全新的产品视频任务？”。仅在用户确认“是”后发送完整清单，确认“否”则继续当前任务。等待切换确认或清单回复期间不执行任何生产动作。上一个任务的单次自动执行、预算和付费授权不得继承。
```

- [ ] **Step 3: 更新启动清单的场景说明**

将 `startup-checklist.md` 的 `### 新任务意图识别` 小节替换为：

```markdown
### 任务窗口路由

在全新的 Codex 任务窗口中，第一条用户消息无论内容是什么，都发送本文件规定的完整三段式清单；不要求出现产品、视频或“开始新任务”等关键词。用户同一条消息中已提供的信息自动带入并标记为 `已提供`。

在已有任务窗口中，普通消息继续当前任务，不发送新任务清单。当用户表达“开始新任务、开始新项目、换个产品、再开一批”或同义意图时，只问一次：“是否开始全新的产品视频任务？”用户确认“是”后发送完整清单，确认“否”则继续当前任务。确认前不得扫描、建批次、查询价格、生图、dry-run 或付费提交。上一个任务的单次自动执行、预算和付费授权不得继承。

| 场景 | 行为 |
|---|---|
| 新窗口第一条消息为“你好” | 立即发送完整启动清单 |
| 新窗口第一条消息包含产品目录和卖点 | 发送清单，并把已有字段标记为已提供 |
| 已有窗口说“开始新任务” | 只询问“是否开始全新的产品视频任务？” |
| 已有窗口确认“是” | 发送完整启动清单 |
| 已有窗口确认“否” | 继续当前任务，不发送新任务清单 |
| 已有窗口普通追问 | 继续当前任务，不发送新任务清单 |
```

- [ ] **Step 4: 同步当前生效副本并校验文本一致性**

使用 `apply_patch` 把 Step 2 和 Step 3 的相同改动应用到用户目录中的 `SKILL.md` 与 `startup-checklist.md`，然后运行：

```powershell
$sourceSkill = Get-Content -LiteralPath "D:\0-AI 项目\ayh-h3\skill-package\product-video-pipeline\SKILL.md" -Raw
$activeSkill = Get-Content -LiteralPath "C:\Users\Administrator\.agents\skills\product-video-pipeline\SKILL.md" -Raw
$sourceChecklist = Get-Content -LiteralPath "D:\0-AI 项目\ayh-h3\skill-package\product-video-pipeline\references\startup-checklist.md" -Raw
$activeChecklist = Get-Content -LiteralPath "C:\Users\Administrator\.agents\skills\product-video-pipeline\references\startup-checklist.md" -Raw
if ($sourceSkill -ne $activeSkill) { throw "SKILL.md 源码与生效副本不一致" }
if ($sourceChecklist -ne $activeChecklist) { throw "startup-checklist.md 源码与生效副本不一致" }
```

Expected: 命令安静退出，退出码为 0。

- [ ] **Step 5: 运行离线自检并确认 GREEN**

Run:

```powershell
python "C:\Users\Administrator\.agents\skills\product-video-pipeline\scripts\self_test.py"
```

Expected: 输出 `product-video-pipeline 自检通过（未联网、未产生费用）`，退出码为 0。

- [ ] **Step 6: 检查差异并提交实现**

```powershell
git diff --check -- "skill-package/product-video-pipeline/SKILL.md" "skill-package/product-video-pipeline/references/startup-checklist.md"
git add -- "skill-package/product-video-pipeline/SKILL.md" "skill-package/product-video-pipeline/references/startup-checklist.md"
git commit -m "feat: route new task windows to product video startup"
```

### Task 3: 完成窗口级人工验收与学习记录

**Files:**
- Create: `Y:\0-AI训练\光合视频\轻便侠218 产品图片\生成视频\20260831_批次001\V001_防滑安全_待生成\_工作文件\任务状态\全局任务窗口路由验证.json`

**Interfaces:**
- Consumes: 已生效的全局规则和用户在新、旧两个 Codex 窗口中的实际观察结果。
- Produces: 区分“静态测试通过”和“真实窗口验证通过”的学习证据，防止仅凭字符串测试宣布完成。

- [ ] **Step 1: 在当前已有窗口验证切换询问**

用户发送“开始新任务”时，预期只收到：

```text
是否开始全新的产品视频任务？
```

此时不得出现目录扫描、价格查询、媒体生成、dry-run 或付费请求。

- [ ] **Step 2: 在全新窗口验证任意首条消息**

新建一个 Codex 任务窗口，发送：

```text
你好
```

Expected: 回复中完整出现 `你需要提供的内容`、`本次配置明细`、`请你回复`，且没有执行“你好”之外的任何生产动作。

- [ ] **Step 3: 写入验证记录**

使用 `apply_patch` 创建以下 JSON；只有两个窗口场景都由用户确认后才能把 `status` 写为 `passed`：

```json
{
  "rule": "global_product_video_task_window_router",
  "date": "2026-09-01",
  "static_self_test": "passed",
  "existing_window_confirmation": "passed",
  "fresh_window_first_message": "passed",
  "fresh_window_message": "你好",
  "status": "passed",
  "network_used": false,
  "paid_action_used": false
}
```

- [ ] **Step 4: 最终核验提交与工作区边界**

Run:

```powershell
git log -3 --oneline
git status --short
```

Expected: 最近记录包含 `test: require global product video task router` 和 `feat: route new task windows to product video startup`；未跟踪的用户文件保持原样，没有被提交或删除。窗口级验证 JSON 位于用户指定学习目录，不纳入项目 Git。
