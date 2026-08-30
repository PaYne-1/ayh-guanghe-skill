# AutoDL.Art MiniMax-H3

## 已固定参数

```text
默认新视频工作流 ID：`minimax_h3_lightx2v_v5_15s`
默认提交端点：https://www.autodl.art/api/v1/comfyui/comfyui_workflow/minimax_h3_lightx2v_v5_15s
兼容工作流别名：`minimax_h3_lightx2v`
查询模板：https://www.autodl.art/api/v1/comfyui/comfyui_workflow/result/{task_id}
模型：MiniMax-H3 15 秒首尾帧生视频工作流
时长：15 秒
比例：9:16
默认分辨率：768P
可选分辨率：2K（必须在任务开始前确认）
AIGC 画面水印：当前工作流不暴露水印字段，不向请求加入旧接口的 `aigc_watermark`
声音：模型生成老人和一名陪护者或家属的双角色对话；无 BGM
```

AutoDL 可能调整请求字段、鉴权格式和价格。任务开始时必须查看当时的 API 能力说明，并把实际 payload、Bearer/raw 鉴权方式、会员单价、查询时间和预算写入启动确认单。不要把历史价格永久写死。

## 固定首尾帧 Payload

每条新视频只使用首尾帧工作流。请求字段为 `prompt`、`duration`、`resolution`、`first_frame` 和 `last_frame`：

- `first_frame` 使用用户已明确通过且哈希有效的 `2160×3840` 一级 `分镜图.png`。
- `last_frame` 使用用户已明确通过且哈希有效的 `2160×3840` 一级 `尾帧图.png`，尾帧不得复用首帧。
- 图片通过公网 URL 或 `data:image/...;base64,...` 传入；不得提交本地文件路径。
- `duration` 固定为 `15`。
- `resolution` 使用 `768p竖` 或任务开始时确认的工作流枚举值。
- `prompt` 必须逐句标注两个 `speaker_id`，并明确写出覆盖整个 0–15 秒的“一镜到底、连续平稳运镜、完整双人对话口播”。

合理尾帧表现主体继续前进约 1–1.5 米后的背景透视、车轮转动和陪护者下一步步态，同时保持人物比例、安全边距、曝光、白平衡、整体亮度和产品结构。产品原图只用于校正结构，不能覆盖已通过分镜的构图和人物关系。

首尾帧只加强端点约束。视频全程禁止切镜、跳切、转场和景别突变；运镜始终缓慢、连续、平稳；双角色全部口播必须按自然聊天语速说完且尾句不截断。缺少任一规则时不得 dry-run 或付费提交。

该工作流没有独立参考音频输入时，允许使用模型原生双角色对话音轨。`prompt` 必须规定陪护者提问、老人回答唯一卖点，并由脚本指定角色说出下单类行动指令。生成后必须逐句核验台词、说话顺序、角色归属、语音可理解度和下单类结尾；出现自问自答、串角色、漏句、听不懂或缺少下单指令时判为不合格。

保存最终 payload 为本条 `_工作文件/任务状态/提交请求.json`。请求哈希必须覆盖完整 payload；同时保存 `first_frame` 与 `last_frame` 的候选路径、SHA-256、尺寸和结构检查结果。因为服务端字段可能更新，便携脚本读取任务开始时确认的完整 JSON payload，不猜测未知字段。

历史任务中出现的 `minimax_h3_image_audio_to_video_v2_15s` 只作为既有提交证据保留，不得用于新任务、V01 或 V02 提交。

## 先 dry-run

```powershell
python scripts/autodl_h3.py submit `
  --workflow-id minimax_h3_lightx2v_v5_15s `
  --payload "_工作文件/任务状态/提交请求.json" `
  --dry-run `
  --state "_工作文件/任务状态/提交预览.json"
```

dry-run 会在本地拒绝缺少 `first_frame`、`last_frame`、固定时长或三项全程提示词规则的 payload，不联网、不产生费用。检查工作流端点、完整 payload、分辨率、两张一级首尾帧各自的有效通过事件、不同 SHA-256 和 `request_hash` 后，才能请求付费授权。

## 正式提交

先在安全环境变量中设置密钥，不要把密钥写进技能、任务文件或聊天记录。

```powershell
$env:AUTODL_API_KEY = "从安全凭据读取"
$env:AUTODL_AUTH_SCHEME = "bearer"  # API 文档要求原始 Token 时改为 raw
python scripts/autodl_h3.py submit `
  --workflow-id minimax_h3_lightx2v_v5_15s `
  --payload "_工作文件/任务状态/提交请求.json" `
  --confirm-paid YES `
  --state "_工作文件/任务状态/AutoDL提交结果.json"
```

成功后立即运行 `workflow_cli.py record-task`，把 `task_id` 同步到项目和批次。若客户端超时且无法判断服务端是否已收到，不得自动重复提交。

## 查询与下载

```powershell
python scripts/autodl_h3.py poll --task-id "task_id" --interval 20 --max-wait 3600 --state "_工作文件/任务状态/查询结果.json"
python scripts/autodl_h3.py download --url "结果URL" --output "_工作文件/生成过程/视频候选.mp4"
```

正式提交后立即把任务标识保存到 `_工作文件/任务状态/任务信息.json`。提交请求、提交预览、查询日志、查询结果和 AutoDL 原始响应也全部进入 `_工作文件/任务状态`，不得写在单条任务第一级。

成功 URL 有效期可能较短，应立即下载。脚本使用 `.part` 临时文件和 4 次下载重试；下载后仍要用 ffprobe 检查容器、15 秒、9:16、分辨率、双角色音轨和可解码画面。
