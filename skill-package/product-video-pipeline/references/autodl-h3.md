# AutoDL.Art MiniMax-H3

## 已固定参数

```text
默认新视频工作流 ID：`minimax_h3_image_audio_to_video_v2_15s`
默认提交端点：https://www.autodl.art/api/v1/comfyui/comfyui_workflow/minimax_h3_image_audio_to_video_v2_15s
无音频多图工作流 ID：`minimax_h3_lightx2v_v5_15s`（仅按明确方案使用）
查询模板：https://www.autodl.art/api/v1/comfyui/comfyui_workflow/result/{task_id}
模型：MiniMax-H3 15 秒多图生视频工作流
时长：15 秒
比例：9:16
默认分辨率：768P
可选分辨率：2K（必须在任务开始前确认）
AIGC 画面水印：当前工作流不暴露水印字段，不向请求加入旧接口的 `aigc_watermark`
声音：先生成并验收独立口播音轨；视频阶段同步口型 + 轻微环境声；无 BGM
```

AutoDL 可能调整请求字段、鉴权格式和价格。任务开始时必须查看当时的 API 能力说明，并把实际 payload、Bearer/raw 鉴权方式、会员单价、查询时间和预算写入启动确认单。不要把历史价格永久写死。

## Payload 原则

- 使用已验收的 `分镜图.png` 作为 `ref_image_0`，通过公网 URL 或 `data:image/...;base64,...` 传入；不得把本地文件路径直接提交给服务器。
- `prompt` 包含人物清单、台词、说话顺序、音色年龄感、唯一卖点、固定镜头和画面限制。
- `duration` 固定为 `15`，`resolution` 使用 `768p竖` 或任务开始时确认的工作流枚举值。
- 保存最终 payload 为本条 `提交请求.json`，请求哈希必须覆盖 `prompt`、`ref_image_0`、`resolution` 和 `duration`。

因为服务端字段可能更新，便携脚本直接读取用户在任务开始时确认的完整 JSON payload，不猜测未知字段。

## 行驶双人对话首尾帧流程

当画面需要轮椅真实向前行驶、老人和一名陪护者/家属完成双角色对话，并尽量保持已通过分镜构图时，优先使用首尾帧工作流 `minimax_h3_lightx2v`。请求字段为 `prompt`、`duration`、`resolution`、`first_frame`、`last_frame`；正式提交仍需用户确认方案和当次费用。

`first_frame` 使用已通过的 `2160×3840` 分镜图；`last_frame` 使用根据该分镜独立生成并通过结构检查的合理行驶尾帧，尾帧不得复用首帧。尾帧表现继续前进约 1–1.5 米后的背景透视、车轮转动和陪护者下一步步态，同时保持人物比例、安全边距、曝光、白平衡、整体亮度和产品结构。产品原图只用于校正结构，不能覆盖已通过分镜的构图和人物关系。

首尾帧请求的 `prompt` 必须包含一个覆盖整个0–15秒的全程规则段，明确写出“一镜到底、连续平稳运镜、完整口播”。这三项约束适用于首帧、全部中间帧和尾帧，不得只约束首帧和尾帧：全程禁止切镜、跳切、转场和景别突变；运镜始终缓慢、连续、平稳并保持分镜构图；全部口播按自然聊天语速说完且尾句不截断。缺少任一项时不得进入付费提交。

该工作流没有独立参考音频输入时，允许使用模型原生双角色对话音轨。`prompt` 必须逐句标注说话人，并规定提问者/陪护者提问、老人/乘坐者回答卖点、结尾由脚本指定角色说出下单类行动指令。生成后必须逐句核验台词、说话顺序、角色归属、语音可理解度和下单类结尾；出现自问自答、串角色、漏句、听不懂或缺少下单指令时判为不合格。

## 默认多图多音频流程

新视频默认使用 `minimax_h3_image_audio_to_video_v2_15s`。提交端点为 `/api/v1/comfyui/comfyui_workflow/minimax_h3_image_audio_to_video_v2_15s`；字段包括 `prompt`、`duration`、`resolution`、`ref_image_0` 至 `ref_image_8`、`ref_audio_0` 至 `ref_audio_2`。

先从已确认脚本生成独立口播音轨，核对全部台词、说话顺序和音色，并确认完整时长在14秒内。新视频不得依赖上一版音轨，也不得为了省略音轨步骤而让视频模型现场重新创作对白。使用已通过分镜作为 `ref_image_0`、原始产品图作为辅助产品参考，并把本条新生成且已验收的独立口播音轨作为 `ref_audio_0`。失败恢复任务可以在人工确认后复用上一版已验收完整的音轨。

对话式脚本必须先按 `speaker_id` 分别生成各人物语音，再按脚本时间线合成为一个 `ref_audio_0`。每个不同说话人的音色必须可区分并匹配人物身份、性别和年龄感；系统自动逐段核验说话人和台词，不设置用户试听确认节点。单一音色包办多人台词、自问自答或说话顺序错误的音轨不得提交。

`prompt` 只描述广角行驶动作、一镜到底、连续平稳运镜、人物产品全程完整和音轨同步，不重复创作台词。音频和图片必须通过公网 URL 或受支持的 `data:...;base64,...` 传入；付费前先 dry-run 并核对工作流、素材哈希、时长、分辨率、音轨生成费用、视频费用和当时价格。

## 先 dry-run

```powershell
python scripts/autodl_h3.py submit `
  --workflow-id minimax_h3_image_audio_to_video_v2_15s `
  --payload "提交请求.json" `
  --dry-run `
  --state "提交预览.json"
```

检查工作流端点、payload、分辨率和 request_hash。dry-run 不联网、不产生费用。

## 正式提交

先在安全环境变量中设置密钥，不要把密钥写进技能、任务文件或聊天记录。

```powershell
$env:AUTODL_API_KEY = "从安全凭据读取"
$env:AUTODL_AUTH_SCHEME = "bearer"  # API 文档要求原始 Token 时改为 raw
python scripts/autodl_h3.py submit `
  --workflow-id minimax_h3_image_audio_to_video_v2_15s `
  --payload "提交请求.json" `
  --confirm-paid YES `
  --state "AutoDL提交结果.json"
```

成功后立即运行 `workflow_cli.py record-task`，把 task_id 同步到项目和批次。若客户端超时且无法判断服务端是否已收到，不得自动重复提交。

## 查询与下载

```powershell
python scripts/autodl_h3.py poll --task-id "task_id" --interval 20 --max-wait 3600 --state "查询结果.json"
python scripts/autodl_h3.py download --url "结果URL" --output "视频.mp4"
```

成功 URL 有效期可能较短，应立即下载。脚本使用 `.part` 临时文件和 4 次下载重试；下载后仍要用 ffprobe 检查容器、15 秒、9:16、分辨率、音轨和可解码画面。
