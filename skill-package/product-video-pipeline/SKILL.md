---
name: product-video-pipeline
description: Use only when the user explicitly says 开始产品视频、制作产品视频、生成产品视频、电动轮椅视频、光合视频任务、继续产品视频任务, or explicitly invokes product-video-pipeline. Do not use for unrelated first messages or generic words such as 开始、继续、视频、产品。
---

# 产品短视频流水线

## Overview

把“产品图片 + 卖点”转成可验收的 15 秒竖屏视频项目。Codex、WorkBuddy、Hermes 或其他能读取 Agent Skills 的智能体均使用同一套文件协议；文本模型负责内容，启动确认明确选择 GPT 网页或第三方 API 图片渠道，便携脚本负责目录、校验、AutoDL 任务记录与验收。

## Trigger contract

只在用户明确说出以下任一触发词时启动：`开始产品视频`、`制作产品视频`、`生成产品视频`、`电动轮椅视频`、`光合视频任务`、`继续产品视频任务`，或显式调用 `$product-video-pipeline`。单独出现“开始”“继续”“视频”“产品”等泛化词不触发。

## Required routing

0. **明确触发后才启动**：每次任务明确触发后的第一步，才读 [启动确认单](references/startup-checklist.md) 并完整展示 `你需要提供的内容`、`本次配置明细`、`请你回复` 三个区块；“你好”或普通“继续”不触发新任务。未收到启动回复前，不扫描产品素材、不创建批次、不联网查询、不生图、不 dry-run，也不调用付费接口。
1. **安全接入 API**：首次启动清单不询问 AutoDL API 接入状态或鉴权方式。用户授权验证后直接读取安全环境配置；`AUTODL_AUTH_SCHEME` 未设置时沿用脚本默认值 `bearer`。只有缺少 `AUTODL_API_KEY`，或鉴权实际失败并导致流程无法继续时，才询问并引导用户安全配置；不得要求用户把完整密钥粘贴到聊天中。
2. 用户回复启动清单后，完成实时价格与 V01 总预算确认；dry-run 不联网、不扣费，API 可用或 dry-run 通过都不代表付费授权。
3. 启动时按需读取 [11 节点流程](references/workflow.md)、[内容契约](references/content-contract.md)、[自动复盘与规避规则](references/automatic-learning-rules.md) 及产品配置；详细引用是人工审计文档，运行时不在每个节点反复整篇读入模型上下文。
4. **图片渠道必须在启动确认时明确选择**：可选 `gpt_web` 或 `third_party_api`。第三方配置仅保存 API 名称、HTTPS 地址、模型、环境变量名及预算字段，绝不保存 API 密钥明文；不进行人工图片审核，也不调用模型进行二次视觉审核。本地免费技术检查通过后脚本自动晋升，见 [生图路由](references/image-generation-routing.md)。
5. DeepSeek 只用于批次内容创作和异常修复，必须由 `pipeline_policy.json` 的批次/单视频调用计数器限制。生图接收、技术检查、哈希、轮询、下载、晋升、审计和恢复不调用 DeepSeek。
6. 视频 V01 只能在已批准总预算内提交；失败后 V02 必须取得该视频的单独费用授权，不得提交 V03。最终视频始终由用户人工验收，见 [AutoDL H3](references/autodl-h3.md)、[验收与学习](references/review-learning.md) 和 [交付契约](references/delivery-contract.md)。

## Start

先完成每次任务必需的三段式启动沟通并获得明确回复；以下命令只能在回复后的验证阶段运行。

只读取用户给定产品文件夹第一层图片。卖点直接使用，一个卖点对应一条独立视频；数量多于卖点时从第一个卖点开始分配余数。

```powershell
python scripts/workflow_cli.py init `
  --product-dir "用户产品文件夹" `
  --product-name "产品名称" `
  --selling-point "卖点一" --selling-point "卖点二" `
  --total 2 --mode learning --resolution 768P `
  --max-budget 20 --cover-reference-dir "封面图参考文件夹" `
  --image-provider gpt_web
```

使用第三方 API 时改为 `--image-provider third_party_api --image-api-config "非机密配置 JSON 文件"`；该 JSON 只能包含 `api_name`、`base_url`、`model`、`api_key_env`、`unit_price_yuan` 与 `batch_budget_yuan`，密钥只通过 `api_key_env` 指向的环境变量提供。

打开生成的 `启动确认单.json`，向用户一次确认。两种模式的图片节点都不做人工或模型视觉审核，下载结果通过免费技术检查后自动晋升；最终视频都进入批量人工验收。

## Runtime loop

1. 完成启动清单和预算确认，在启动 JSON 填入 `unit_price_yuan` 或逐项 `prices_by_video`，再调用 `pipeline_runner.py approve-start --batch "批次目录" --approved-budget "批准预算" --estimated-v01-total "V01总价"`。脚本绑定项目 ID/数量、单价、总价、分辨率及工作流；配置变更不继承付费授权。
2. 调用 `pipeline_runner.py next` 并只执行返回的一个外部动作。
3. `BATCH_CONTENT_REQUIRED` 按 `prompt_path` 为指定 `video_ids` 写入内容 JSON，调用 `accept-content --action-id "动作ID"`。`GPT_WEB_IMAGE_REQUIRED` 按 `reference_paths` 上传参考图并完成一次网页生成/下载，再调用 `pipeline_runner.py accept-image --action-id "动作ID"`。动作在返回前已保留次数；恢复时沿用同一 `action_id`，不得自行重发生成。
4. 图片不进行人工审核，也不调用模型进行二次视觉审核；技术检查和自动晋升由脚本完成。
5. `LOCAL_WORK_REQUIRED` 或 `VIDEO_POLL_PENDING` 时执行 `run-local --batch "批次目录"`；脚本顺序生成首尾帧 payload、执行 AutoDL、保存证据并生成报告。若含 `recovery_required`，先修复列明的本地环境问题，再用同一命令恢复原版本/原 task_id，不重新付费。轮询、下载、哈希、晋升、审计和恢复不得调用 DeepSeek。`run-local --dry-run` 只返回 `DRY_RUN_COMPLETE` 预览，不推进真实进度。
6. 动作完成后再次调用 `next`。`USER_FINAL_REVIEW_REQUIRED` 打开 `report_path`，只验收报告中已有真实候选的项目，再调用 `complete-review`；通过/不通过都绑定报告路径、哈希和版本。未完成的兄弟项目保持可恢复。`USER_RERUN_APPROVAL_REQUIRED` 只为已有真实 V01 提交且获批的项目调用 `approve-rerun`；金额必须等于该项预计费用。`LOCAL_OUTPUT_REPAIR_REQUIRED` 按 `audit_path` 恢复缺失/损坏的已批准产出，再运行 `run-local`，此分支只审计、不生成、不付费。`ITEM_BLOCKED` 时其他项目继续，`BLOCKED` 或 `ITEMS_BLOCKED` 展示已落盘的原因，`DONE` 才算完成。
7. 不得把完整日志粘贴回模型上下文；只读取脚本输出的紧凑 JSON。

默认分别限制批次内容创建 1 次、内容校验修正 1 次、必要异常诊断 1 次；GPT 网页图片单独计数。必要诊断先运行 `reserve-diagnostic --batch "批次目录" --video-id "视频ID" --reason "简短原因"`，按返回动作完成后用 `accept-diagnostic --action-id "动作ID" --result "诊断JSON"` 接收。诊断只记录建议，不扩大付费或重生图授权。

## Execution contract

- 每条项目固定为轮椅真实向前行驶、老人和一名陪护者或家属进行双人对话；只生成一套内容、一张正式分镜首帧、一张合理尾帧、一张封面图和一个视频。
- 单条任务目录第一级只保留 `标题.txt`、`发布正文.txt`、`话题标签.txt`、`分镜图.png`、`尾帧图.png`、`封面图.png`、按发布标题清洗命名的 `.mp4` 七项最终产出和 `_工作文件`；所有状态、提示词、音轨、验收证据、实验文件及历史版本必须写入 `_工作文件` 的对应分类，禁止散落在第一级。
- 七项最终产出都必须在 `_工作文件/验收记录/产出验收记录.json` 中绑定候选路径和 SHA-256。启动确认是内容与图片前置节点的持续执行授权；图片仅通过本地免费技术检查后记录该授权并晋升，不再逐节点询问。最终视频仍必须由用户明确通过。
- `review-output` 会先保存不可变验收候选快照，再追加验收事件；重新生成同名候选时旧候选进入 `_工作文件/历史版本/候选版本`，不得覆盖或破坏既有验收证据。
- 所有分镜图默认生成竖屏 4K：`2160×3840`、`9:16`。这是分镜图固定默认值；视频仍按启动确认单选择 `768P` 或 `2K`，两者不得混用。
- 图片技术失败的重试次数由 `pipeline_policy.json` 限制；耗尽后只暂停该项目，其他项目继续。
- 视频为 V01 初次生成。验收失败时先反馈问题与证据；只有用户对该视频单独批准 V02 费用后才允许重跑，启动时的批次授权不等于 V02 授权。V02 不通过时不得提交 V03。
- 每条项目在分镜通过免费技术检查并自动晋升后，必须把该 `2160×3840` 分镜作为 `first_frame`，再独立生成合理尾帧作为 `last_frame`。尾帧通过相同技术检查、绑定独立 SHA-256 后自动晋升为一级 `尾帧图.png`；尾帧不得复用首帧。
- 所有新视频固定使用 `minimax_h3_lightx2v_v5_15s`。一级 `分镜图.png` 与 `尾帧图.png` 必须具有各自有效的通过事件和不同 SHA-256；本地语义字段为 `first_frame`、`last_frame`，提交时映射为服务端当前字段；任一素材或通过证据缺失时不得 dry-run 或付费提交。
- 每套脚本必须恰好包含老人和一名陪护者或家属两个不同的 `speaker_id`，两人都在画面中真实对话；陪护者身份按脚本确定，不固定为女儿。模型原生音轨必须让两个角色的声音与身份、性别和年龄感匹配且彼此可区分；少角色、同一人包办全部台词、音色不可区分、顺序错误或自问自答时不得通过视频验收。
- AutoDL 成功返回后立即保存 `task_id`；未知提交状态不得盲目重提。
- API 整体失效、余额不足、预算超限或必要配置失效才暂停整个批次。
- 生成完成不等于交付完成。任务只有在七项最终产出审计全部有效后才算完成：视频按发布标题命名并位于一级目录、媒体可解码、`audit-outputs` 无缺失/撤下/错误、任务状态已更新为 `COMPLETED`。每次返回 `DONE` 前，运行器必须重新审计整批所有视频的七项产出，不依赖以前的 `COMPLETED` 标记或仅审计本次验收清单；已完成兄弟项目缺失或损坏时进入本地交付修复，不因此开放 V02。

## Quick reference

| 任务 | 命令/规则 |
|---|---|
| 内容落盘 | `workflow_cli.py validate-content` |
| 封面文字 | GPT 一次生成包含准确标题的完整封面；禁止代码叠字，生成结果不做二次文字审核 |
| 明确验收产出 | `workflow_cli.py review-output`，`passed` 后才晋升一级目录 |
| 审计一级产出 | `workflow_cli.py audit-outputs`，撤下无有效通过证据的文件 |
| 付费前检查 | `autodl_h3.py submit --dry-run` |
| 正式提交 | 运行器 `run-local` 在绑定的批准清单内提交；不跳过运行器直接调用付费客户端 |
| 批量验收 | 打开运行器 `USER_FINAL_REVIEW_REQUIRED` 返回的 `report_path` |
| 完成交付 | 用户通过视频 → `review-output` → 标题化 `.mp4` → `audit-outputs` 全绿 → `COMPLETED` |
| 跨 Agent 安装 | 读 [安装说明](references/install.md) |

## 已验证纠正规则矩阵

| 失败表现 | 后续强制动作 | 完成证据 |
|---|---|---|
| 启动阶段重复询问 Key 或鉴权 | 回复后直接检查安全环境，鉴权缺省 `bearer`；只有 Key 缺失或真实鉴权失败才询问 | 配置检查或明确阻断证据 |
| 自动模式每个节点都停下来确认 | 启动和付费授权后连续完成六项前置产出，只在最终视频、失败重跑或硬阻断处暂停 | 前置产出验收事件绑定本批次自动授权 |
| 先做无字底图再用代码叠字 | GPT 一次生成画面、版式和准确标题，下载后做本地技术检查 | 完整封面原图、提示词与候选 SHA-256 |
| 自动验收失败后直接付费重跑 | 先展示候选和失败证据，再询问是否重跑 | 用户对该次重跑的明确授权 |
| 用户认定合格但视频未进入一级目录 | 对指定候选追加 `passed`，保留旧 `failed`，立即晋升标题化文件 | 最新通过事件与一级文件 SHA-256 一致 |
| `标题.txt` 含发布标题和封面标题 | 文件名只解析 `发布标题：` 行 | 一级 `.mp4` 不含封面标题 |
| 生成结束后提前宣告完成 | 审计七项产出、全片解码、更新 `COMPLETED` 后再交付 | `audit-outputs` 无 missing/demoted/errors |

## Common mistakes

- 不要在节点中途才询问模型、API、配音、2K 或预算。
- 不要把标题、脚本或分镜沉淀为素材库；只沉淀产品独立卖点和已验证规则。
- 不要用自动评分替代人工视频验收。
- 不要因自动验收不通过直接提交重跑；先反馈并取得该次明确授权。
- 不要把单条失败扩大为整个批次失败。
- 不要在节点获批后停住等待无必要的“继续”；按交付契约推进到下一审批点。
- 不要用固定名 `视频.mp4` 作为最终交付名；必须使用清洗后的发布标题。
