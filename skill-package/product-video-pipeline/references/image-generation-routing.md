# 生图渠道路由

## 选择和封存

启动回复必须向用户同时提供三个选项：`本机 Codex 界面`、`ChatGPT 网页端`、`第三方 API`。生图渠道必须选择其中一项；三项平级，不设默认渠道，不规定尝试顺序，也不得自动替用户选择。选择后在批次内锁定；已锁定生图渠道故障时不得自动切换到另一渠道。

内部标识分别为 `codex`、`chatgpt_web`、`third_party_api`。前两项只使用当前登录会话，不使用服务器端 OpenAI API；第三方 API 仅使用封存的 `api_name`、`base_url`、`model`、`api_key_env` 和可选的 `unit_price_yuan`，不保存密钥值。

用户只确认本批次最高总预算。预算仅用于视频费用。第三方图片的 `image_budget_ledger` 仅记录独立费用信息，不参与预算拦截；缺少单价不阻止 init 或生成，费用记录为未知而非零。图片和文本可能由服务商另行收费，不计入视频预算。

## 动作与提交

不强制4K，不要求精确2160×3840。`pipeline_policy.json` 中 target_width/target_height 是旧版兼容字段，不再作为请求或验收尺寸。按渠道文档映射实际支持的尺寸参数，默认 `size: auto` 并在提示词明确9:16；`aspect_ratio` 是动作要求，不代表所有接口都有同名参数。若渠道不支持 auto，使用其已确认支持的9:16原生尺寸，不擅自虚构4K型号。下载原始文件检查真实像素，不能用页面预览代替原图。

`next` 按已选渠道返回 `CODEX_IMAGE_REQUIRED`、`CHATGPT_WEB_IMAGE_REQUIRED` 或 `THIRD_PARTY_IMAGE_REQUIRED`，均包含真实参考图绝对路径、提交提示词路径和 `size: auto`、`aspect_ratio: 9:16`、`native_resolution_required: true`。宿主只执行该动作，下载后用：

```powershell
python scripts/pipeline_runner.py accept-image --batch "批次目录" --action-id "动作ID" --source "下载文件"
```

分镜、尾帧和封面均要求**产品参考图是唯一产品依据**，禁止用文字重新描述产品外观。渠道直接生成**渠道支持的原生分辨率** PNG；**禁止本地放大**、拉伸、裁切、补画或重绘。运行器仅允许可解码、9:16画幅（允许1像素取整误差）、RGB 转换和 SHA-256 校验，不进行人工图片审核或模型视觉审核。

技术失败使用同一渠道和原动作的恢复/重试流程。`image-failed --submission-state not_sent|sent|unknown` 记录结算：`not_sent` 释放未用预留；`sent` 计入成本；默认 `unknown` 保留成本并阻止自动重试。

## 人工反馈定位知识（不得注入生成提示词）

如用户指出候选与产品参考图不一致，只记录候选路径、哈希、时间点和反馈；由后续显式 V02 决定是否重做。不得把任何产品组件、颜色、形状或结构描述写回图片提示词。
