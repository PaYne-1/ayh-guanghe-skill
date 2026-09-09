# 生图渠道路由

## 选择和封存

启动回复选择 `GPT 网页端` 或 `第三方 API`，两者批次内锁定，禁止自动切换。已锁定生图渠道在故障时仍不得自动回退到另一渠道。`gpt_web` 只使用当前登录浏览器会话，不使用服务器端 OpenAI API；第三方 API 仅使用封存的 `api_name`、`base_url`、`model`、`api_key_env`、`unit_price_yuan`，不保存密钥值。

用户只确认本批次最高总预算。第三方图片成本由运行器在内部 `image_budget_ledger` 结算，受已封存的总预算和图片份额限制；没有独立的用户图片预算。

## 动作与提交

`next` 返回 `GPT_WEB_IMAGE_REQUIRED` 或 `THIRD_PARTY_IMAGE_REQUIRED`，均包含真实参考图绝对路径、提交提示词路径和 `width: 2160`、`height: 3840`、`native_resolution_required: true`。宿主只执行该动作，下载后用：

```powershell
python scripts/pipeline_runner.py accept-image --batch "批次目录" --action-id "动作ID" --source "下载文件"
```

分镜、尾帧和封面均要求**产品参考图是唯一产品依据**，禁止用文字重新描述产品外观。渠道直接生成**原生2160×3840** PNG；**禁止本地放大**、拉伸、裁切、补画或重绘。运行器仅允许可解码、尺寸精确、RGB 转换和 SHA-256 校验，不进行人工图片审核或模型视觉审核。

技术失败使用同一渠道和原动作的恢复/重试流程。`image-failed --submission-state not_sent|sent|unknown` 记录结算：`not_sent` 释放未用预留；`sent` 计入成本；默认 `unknown` 保留成本并阻止自动重试。

## 人工反馈定位知识（不得注入生成提示词）

如用户指出候选与产品参考图不一致，只记录候选路径、哈希、时间点和反馈；由后续显式 V02 决定是否重做。不得把任何产品组件、颜色、形状或结构描述写回图片提示词。
