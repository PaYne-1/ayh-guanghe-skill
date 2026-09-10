# API 永久配置向导

## 触发边界

用户明确说出 `配置api` 时，只进入 API 配置向导。不得触发产品视频启动清单，不扫描产品目录、不创建批次、不查询媒体价格、不生图、不运行视频 dry-run，也不调用任何付费接口。

配置成功只代表凭据可供后续读取，不代表用户授权第三方生图或 AutoDL 视频付费提交。

## 需要配置的 API

| 类型 | 必需性 | 用途 | 配置项 |
|---|---|---|---|
| AutoDL.Art 视频 API | 必需 | MiniMax-H3 视频生成 | `AUTODL_API_KEY`、`AUTODL_AUTH_SCHEME` |
| 第三方生图 API | 可选 | 用户选择第三方渠道时生成分镜、尾帧和封面 | 服务商、HTTPS `base_url`、模型、API Key、单张价格 |
| 第三方文本生成 API | 可选 | 不使用当前 Agent 原生文本能力时生成策划和文案 | 服务商、HTTPS `base_url`、模型、API Key |

本机 Codex 生图和 ChatGPT 网页端生图使用登录状态，不需要 API Key。

## 固定交互

1. 运行 `python scripts/api_config.py status`，向用户展示三类 API 的“已配置/未配置”、非敏感字段和密钥末四位。
2. 询问本次配置或更换 `autodl`、`image`、`text` 中的哪一项；用户已经明确指定时直接采用，不重复询问。
3. 使用交互式终端运行：

```powershell
python scripts/api_config.py configure --category autodl
python scripts/api_config.py configure --category image
python scripts/api_config.py configure --category text
```

4. 完整 API Key 必须由用户在终端隐藏输入中粘贴。不得要求用户在聊天中发送，不得把密钥放入命令行参数。
5. 工具将配置永久保存到 Windows 当前用户环境变量。只覆盖本次选择的类别，其他配置保持不变。
6. 回复只报告类别、保存范围、验证结论和密钥末四位。

## 永久环境变量

```text
AUTODL_API_KEY
AUTODL_AUTH_SCHEME

PRODUCT_VIDEO_IMAGE_API_PROVIDER
PRODUCT_VIDEO_IMAGE_API_BASE_URL
PRODUCT_VIDEO_IMAGE_API_MODEL
PRODUCT_VIDEO_IMAGE_API_KEY
PRODUCT_VIDEO_IMAGE_API_UNIT_PRICE_YUAN

PRODUCT_VIDEO_TEXT_API_PROVIDER
PRODUCT_VIDEO_TEXT_API_BASE_URL
PRODUCT_VIDEO_TEXT_API_MODEL
PRODUCT_VIDEO_TEXT_API_KEY
```

AutoDL 鉴权格式只能是 `bearer` 或 `raw`。第三方 API 的 `base_url` 必须是无内嵌账号、密码、查询串或片段的有效 `https://` 地址。永久生图配置会自动转换为批次所需的非敏感配置，并把密钥变量固定为 `PRODUCT_VIDEO_IMAGE_API_KEY`；批次仍会封存配置和预算，不扩大付费授权。

## 安全与验证

- 状态和日志只显示密钥末四位，完整密钥不进入聊天、技能文件、项目文件、JSON 或 Markdown。
- 新配置通过完整性和格式检查后才写入；写入失败时恢复原值。
- 只有服务商提供明确且不扣费的鉴权端点时才允许联网验证。
- 没有安全验证端点时报告“已保存，未联网验证”，不得用生成图片或视频的付费请求试 Key。
- 需要更换时，用户再次说 `配置api`；空白密钥输入表示保留现有密钥。
