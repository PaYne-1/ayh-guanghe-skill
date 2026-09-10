---
name: product-video-pipeline
description: Use only when the user explicitly says 开始产品视频、制作产品视频、生成产品视频、电动轮椅视频、光合视频任务、继续产品视频任务, says 配置api (Latin API suffix is case-insensitive, including 配置api、配置API、配置Api、配置aPi) to manage persistent API settings, or explicitly invokes product-video-pipeline. Do not use for unrelated first messages or generic words such as 开始、继续、视频、产品。
---

# 产品短视频流水线

把“产品参考图 + 卖点”转成可交付的 15 秒竖屏视频。Codex、WorkBuddy、Hermes 等兼容 Agent 使用同一文件协议；文本模型只负责内容，锁定的图片渠道只生成三张原生 4K 图片，运行器负责状态、预算、技术检查、AutoDL 任务和真实路径交付。

## 触发与首次回复

仅在明确产品视频触发词或 `$product-video-pipeline` 出现时，每次任务的第一步读取并完整展示 [启动确认单](references/startup-checklist.md) 的 `你需要提供的内容`、`本次配置明细`、`请你回复` 三个区块。普通“继续”只继续当前任务；换产品或新批次只先问一次是否开始全新任务。

用户明确说 `配置api`（Latin `api` 后缀**不区分大小写**，包括 `配置API`、`配置Api`、`配置aPi`）时，只进入 [API 永久配置向导](references/api-configuration.md)。主机必须先执行 `python scripts/api_config.py prompt`，成功后原样展示其遮罩状态和唯一类别行，再询问用户类别；不得自行拼接状态或类别。命令失败时明确回复“无法读取当前配置状态，永久配置未更改”并停止，绝不可推断为“未配置”。首条回复没有推荐、默认或预选项，唯一有效类别行是：

```text
AutoDL.Art 视频 API / 第三方生图 API / 第三方文本生成 API
```

不得触发产品视频启动清单、扫描目录、创建批次、dry-run 或任何付费调用。密钥只允许在交互式终端隐藏输入，并永久保存到 Windows 当前用户环境变量。

首次回复是唯一的配置与授权交互：自动生产模式的**首次回复同时授权 V01**。先在本地验证价格、预算、渠道与安全环境；只有硬阻断才返回用户。不得要求 `approve-start`、第二次自动启动确认、单独图片预算、图片审核或 V01 语义审核。第三方图片 API 只确认 `api_name`、`base_url`、`model`、`api_key_env`、`unit_price_yuan`，只记录环境变量名，绝不索取密钥。

用户只填写一个 `本批次最高总预算`。它覆盖 V01 视频和初始图片估算；运行器在本地拆分内部台账，不把图片预算作为用户输入，也不把 V02 计入此授权。学习确认模式保留 `approve-start` 和最终人工验收。

## 不可变生成合同

- 每个生成提示词都声明：**产品参考图是唯一产品依据**；直接使用参考图，**禁止用文字重新描述产品外观**，禁止重新设计、补画、删减、替换或推测任何部件。
- 分镜、尾帧、封面均为**原生2160×3840**、9:16、8,294,400 像素；必须由渠道原生生成，**禁止本地放大**。只允许解码和 RGB 转换，不允许空间重采样。
- 视频固定 0–15 秒、一个连续镜头、**固定中远景**。老人、陪护者和完整产品全程处于安全区；无切镜、跳切、转场、景别变化或新增人物/产品。
- 台词清单是封闭合同：每句只出现一次并由指定 `speaker_id` 说出；**非当前说话者嘴巴闭合且完全不发声**；**清单之外零人声**、无画外音、无重复、无改词、无 BGM。

详细规则见 [内容契约](references/content-contract.md)、[生图路由](references/image-generation-routing.md)、[工作流](references/workflow.md)、[AutoDL H3](references/autodl-h3.md)、[交付契约](references/delivery-contract.md)。学习复盘的操作入口是 [验收、反馈与学习](references/review-learning.md)：先记录候选经验，再用 `start-rerun` 建立复跑上下文，最后用 `validate-learning` 以 `passed`、`failed` 或 `inconclusive` 记录验证结果。自动模式只读取已验证的正式规则，不把当前自动 V01 的反馈自动升级为规则。

## 运行

```powershell
python scripts/workflow_cli.py init `
  --product-dir "用户产品文件夹" `
  --product-name "产品名称" `
  --selling-point "卖点一" --total 1 --mode auto --resolution 768P `
  --max-budget 20 --image-provider <codex|chatgpt_web|third_party_api>
```

生图渠道必须由用户从 `codex`、`chatgpt_web`、`third_party_api` 三项中明确选择；不设默认值，也没有固定尝试顺序。第三方 API 使用 `--image-provider third_party_api --image-api-config <非敏感JSON路径>`。已锁定生图渠道不可替换。初始化后按以下循环执行，始终只执行返回的一个外部动作：

1. 自动模式首次回复后填写本地价格配置，调用 `pipeline_runner.py next`；学习确认模式才调用 `approve-start`。
2. `BATCH_CONTENT_REQUIRED` 写入内容 JSON 后 `accept-content`；`CODEX_IMAGE_REQUIRED`、`CHATGPT_WEB_IMAGE_REQUIRED` 或 `THIRD_PARTY_IMAGE_REQUIRED` 用 `accept-image` 回传下载文件。渠道批次内锁定，禁止自动切换；图片不进行人工图片审核或模型视觉审核。
3. `LOCAL_WORK_REQUIRED`/`VIDEO_POLL_PENDING` 使用 `run-local`。`run-local --dry-run` 返回 `DRY_RUN_COMPLETE`，不联网、不扣费、不推进状态。
4. 自动 V01 的确定性技术检查通过后自动晋升并交付 `V01_DELIVERED`，状态为 `WAITING_USER_FEEDBACK`。返回的 `video_path` 和 `item_dir` 必须是**真实存在的绝对路径**，并附 SHA-256、技术证据和成本。不得自动判断 V01 语义好坏。
5. 仅在用户反馈后才使用 `request-rerun --batch PATH --video-id ID --reason TEXT` 记录问题。该命令不付费；随后必须对 V02 显式批准单视频费用，才可 `approve-rerun`。V02 进入学习式人工验收，绝不自动 V03。

不得把完整日志粘贴回模型上下文，只读取紧凑 JSON。API 失效、余额不足、总预算不足、缺少安全配置或本地技术失败是硬阻断；其他项目可继续。原生生图动作与 `image_budget_ledger` 是内部台账分类。学习模式的 `review-output` 和 `audit-outputs` 仍绑定明确通过与 SHA-256；自动 V01 不使用这两个审核关卡。

## 产出与路径

单条任务第一级只保留 `标题.txt`、`发布正文.txt`、`话题标签.txt`、`分镜图.png`、`尾帧图.png`、`封面图.png`、按发布标题清洗命名的 `.mp4` 和 `_工作文件`。过程文件按 `_工作文件/任务状态`、`_工作文件/生成过程`、`_工作文件/验收记录`、`_工作文件/历史版本` 分类。学习模式和 V02 只有 `review-output` 记录明确 `passed` 事件并由 `audit-outputs` 复核后，才可保留一级文件；没有明确通过不得保留一级文件。自动 V01 只按新的技术交付合同例外：技术证据和交付哈希有效时交付并等待反馈，不把 `WAITING_USER_FEEDBACK` 伪装为 `COMPLETED`。所有新视频固定使用 `minimax_h3_lightx2v_v5_15s`。
