---
name: product-video-pipeline
description: Use when a user needs batch product short-video planning, storyboard and cover generation, AutoDL.Art MiniMax-H3 submission, task polling, MP4 review, or feedback learning, especially for 爱优护、电动轮椅、淘宝/天猫光合视频。
---

# 产品短视频流水线

## Overview

把“产品图片 + 卖点”转成可验收的 15 秒竖屏视频项目。Codex、WorkBuddy、Hermes 或其他能读取 Agent Skills 的智能体均使用同一套文件协议；平台原生能力负责文本和生图，便携脚本负责目录、校验、AutoDL 任务记录与验收。

## Required routing

0. **安装后首次接入 API**：技能首次使用时先询问 AutoDL API 是否已接入。未接入时，只引导用户安全配置 `AUTODL_API_KEY` 和 `AUTODL_AUTH_SCHEME`，不得先询问产品路径、扫描素材、创建批次或进入策划流程。不得要求用户把完整密钥粘贴到聊天中。
1. API 已接入后，先说明 dry-run 不联网、不扣费，并在用户同意后验证配置。API 接入或 dry-run 通过不代表用户已授权付费提交。
2. 每次任务再读 [启动确认单](references/startup-checklist.md) 和 [11 节点流程](references/workflow.md)。所有 API、模式、分辨率、实时价格和预算一次确认完，再运行。
3. 每次初始化学习模式或自动模式，以及学习模式收到任务相关用户问题时，必须读 [自动复盘与规避规则](references/automatic-learning-rules.md)。进入每个节点前先生成并读取该节点的正式规则清单；仅列出规则但不应用视为未执行。
4. 生成策划前读 [内容契约](references/content-contract.md)。使用爱优护配置时再读 [电动轮椅规则](references/ayh-wheelchair-rules.md) 和 `profiles/爱优护电动轮椅_淘宝天猫光合.json`。
5. 进入任何分镜图或封面底图生图节点前，必须读 [跨智能体生图路由](references/image-generation-routing.md)，严格按照“本机 Codex 界面 → ChatGPT 网页端 → 第三方 API 生图”执行。
6. 提交视频前读 [AutoDL H3](references/autodl-h3.md)。先 dry-run；只有启动确认完成且费用获准后才能付费提交。
7. 成片完成后读 [验收与学习](references/review-learning.md)。最终结果始终由用户人工验收。

## Start

只读取用户给定产品文件夹第一层图片。卖点直接使用，一个卖点对应一条独立视频；数量多于卖点时从第一个卖点开始分配余数。

```powershell
python scripts/workflow_cli.py init `
  --product-dir "用户产品文件夹" `
  --product-name "产品名称" `
  --selling-point "卖点一" --selling-point "卖点二" `
  --total 2 --mode learning --resolution 768P `
  --max-budget 20 --cover-reference-dir "封面图参考文件夹"
```

打开生成的 `启动确认单.json`，向用户一次确认。学习模式审核策划和分镜；自动模式应用已确认规则自动通过前置节点。两种模式的最终视频都进入批量人工验收。

## Execution contract

- 每条项目固定为轮椅真实向前行驶、老人和一名陪护者或家属进行双人对话；只生成一套内容、一张正式分镜首帧、一张合理尾帧、一张封面图和一个视频。
- 单条任务目录第一级只保留 `标题.txt`、`发布正文.txt`、`话题标签.txt`、`分镜图.png`、`尾帧图.png`、`封面图.png`、`视频.mp4` 七项最终产出和 `_工作文件`；所有状态、提示词、音轨、验收证据、实验文件及历史版本必须写入 `_工作文件` 的对应分类，禁止散落在第一级。
- 七项最终产出分别需要用户明确通过，并在 `_工作文件/验收记录/产出验收记录.json` 中绑定候选路径和 SHA-256；自动检查通过、技术指标通过或等待人工验收都不能晋升一级产出。没有明确通过时，一级目录不保留对应文件。
- `review-output` 会先保存不可变验收候选快照，再追加验收事件；重新生成同名候选时旧候选进入 `_工作文件/历史版本/候选版本`，不得覆盖或破坏既有验收证据。
- 所有分镜图默认生成竖屏 4K：`2160×3840`、`9:16`。这是分镜图固定默认值；视频仍按启动确认单选择 `768P` 或 `2K`，两者不得混用。
- 分镜图最多三次；第三次仍不合格时只暂停该项目，其他项目继续。
- 视频为 V01 初次生成，人工不通过后只允许 V02 重跑一次。
- 每条项目在正式分镜通过后，必须把该 `2160×3840` 分镜作为 `first_frame`，再按相同尺寸独立生成一张合理尾帧候选作为 `last_frame`。尾帧候选通过结构检查并由用户明确通过、绑定独立 SHA-256 后，晋升为一级 `尾帧图.png`；尾帧不得复用首帧。
- 所有新视频固定使用 `minimax_h3_lightx2v` 合理尾帧首尾帧方案。一级 `分镜图.png` 与 `尾帧图.png` 必须具有各自有效的通过事件和不同 SHA-256；任一缺失时不得 dry-run 或付费提交。
- 每套脚本必须恰好包含老人和一名陪护者或家属两个不同的 `speaker_id`，两人都在画面中真实对话；陪护者身份按脚本确定，不固定为女儿。模型原生音轨必须让两个角色的声音与身份、性别和年龄感匹配且彼此可区分；少角色、同一人包办全部台词、音色不可区分、顺序错误或自问自答时不得通过视频验收。
- AutoDL 成功返回后立即保存 `task_id`；未知提交状态不得盲目重提。
- API 整体失效、余额不足、预算超限或必要配置失效才暂停整个批次。

## Quick reference

| 任务 | 命令/规则 |
|---|---|
| 内容落盘 | `workflow_cli.py validate-content` |
| 封面文字 | `render_cover.py --title-file _工作文件/生成过程/封面标题.txt`，由程序绘制中文 |
| 明确验收产出 | `workflow_cli.py review-output`，`passed` 后才晋升一级目录 |
| 审计一级产出 | `workflow_cli.py audit-outputs`，撤下无有效通过证据的文件 |
| 付费前检查 | `autodl_h3.py submit --dry-run` |
| 正式提交 | 加 `--confirm-paid YES` |
| 批量验收 | `workflow_cli.py build-review` |
| 跨 Agent 安装 | 读 [安装说明](references/install.md) |

## Common mistakes

- 不要在节点中途才询问模型、API、配音、2K 或预算。
- 不要把标题、脚本或分镜沉淀为素材库；只沉淀产品独立卖点和已验证规则。
- 不要用自动评分替代人工视频验收。
- 不要把单条失败扩大为整个批次失败。
