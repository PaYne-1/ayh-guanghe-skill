# AutoDL.Art MiniMax-H3

## 已固定参数

```text
提交端点：https://www.autodl.art/api/v1/minimax/v2/video_generation
查询模板：https://www.autodl.art/api/v1/minimax/v2/query/video_generation/{task_id}
模型：MiniMax-H3
时长：15 秒
比例：9:16
默认分辨率：768P
可选分辨率：2K（必须在任务开始前确认）
AIGC 画面水印：关闭
声音：模型原生对白 + 轻微环境声；无 BGM；不调用第二份 TTS
```

AutoDL 可能调整请求字段、鉴权格式和价格。任务开始时必须查看当时的 API 能力说明，并把实际 payload、Bearer/raw 鉴权方式、会员单价、查询时间和预算写入启动确认单。不要把历史价格永久写死。

## Payload 原则

- 使用已验收的 `分镜图.png` 作为首帧或图片输入。
- prompt 包含人物清单、台词、说话顺序、音色年龄感、唯一卖点、固定镜头和画面限制。
- `aigc_watermark` 固定为 `false`。
- 保存最终 payload 为本条 `提交请求.json`，请求哈希必须覆盖 prompt、图片哈希、分辨率、时长、比例和水印参数。

因为服务端字段可能更新，便携脚本直接读取用户在任务开始时确认的完整 JSON payload，不猜测未知字段。

## 先 dry-run

```powershell
python scripts/autodl_h3.py submit `
  --payload "提交请求.json" `
  --dry-run `
  --state "提交预览.json"
```

检查端点、payload、分辨率、水印和 request_hash。dry-run 不联网、不产生费用。

## 正式提交

先在安全环境变量中设置密钥，不要把密钥写进技能、任务文件或聊天记录。

```powershell
$env:AUTODL_API_KEY = "从安全凭据读取"
$env:AUTODL_AUTH_SCHEME = "bearer"  # API 文档要求原始 Token 时改为 raw
python scripts/autodl_h3.py submit `
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
