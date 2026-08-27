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
3. 生成策划前读 [内容契约](references/content-contract.md)。使用爱优护配置时再读 [电动轮椅规则](references/ayh-wheelchair-rules.md) 和 `profiles/爱优护电动轮椅_淘宝天猫光合.json`。
4. 提交视频前读 [AutoDL H3](references/autodl-h3.md)。先 dry-run；只有启动确认完成且费用获准后才能付费提交。
5. 成片完成后读 [验收与学习](references/review-learning.md)。最终结果始终由用户人工验收。

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

- 每条项目只生成一个发布标题、一个封面标题、一套脚本、一张最终分镜图、一张封面图和一个视频。
- 分镜图最多三次；第三次仍不合格时只暂停该项目，其他项目继续。
- 视频为 V01 初次生成，人工不通过后只允许 V02 重跑一次。
- AutoDL 成功返回后立即保存 `task_id`；未知提交状态不得盲目重提。
- API 整体失效、余额不足、预算超限或必要配置失效才暂停整个批次。

## Quick reference

| 任务 | 命令/规则 |
|---|---|
| 内容落盘 | `workflow_cli.py validate-content` |
| 封面文字 | `render_cover.py --title-file 封面标题.txt`，由程序绘制中文 |
| 付费前检查 | `autodl_h3.py submit --dry-run` |
| 正式提交 | 加 `--confirm-paid YES` |
| 批量验收 | `workflow_cli.py build-review` |
| 跨 Agent 安装 | 读 [安装说明](references/install.md) |

## Common mistakes

- 不要在节点中途才询问模型、API、配音、2K 或预算。
- 不要把标题、脚本或分镜沉淀为素材库；只沉淀产品独立卖点和已验证规则。
- 不要用自动评分替代人工视频验收。
- 不要把单条失败扩大为整个批次失败。
