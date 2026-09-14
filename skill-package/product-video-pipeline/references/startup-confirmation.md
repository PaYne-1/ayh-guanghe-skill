# 启动确认记录

首次收到新产品视频任务时，只运行当前技能目录的 `python scripts/startup_gate.py prompt` 并完整转发三个区块。不要自行概括或添加选项；本次用户已提供内容可填入对应字段。未回复前不进行其他任务操作。

用户填写所有字段并明确确认后，助手创建以下 JSON。值必须来自本次用户提供或确认的清单，不能复制示例值、历史记忆或旧确认记录。user_reply 保留本次确认原文，不包含 API 密钥。此记录不是额外一次确认，不要求自动模式 approve-start。

```json
{
  "confirmed": true,
  "user_reply": "本次用户明确确认原文",
  "fields": {
    "product_dir": "用户提供的产品目录",
    "product_name": "用户提供的产品名称",
    "selling_points": ["用户提供的卖点"],
    "total": 1,
    "mode": "auto",
    "resolution": "768P",
    "max_budget": "用户提供的预算",
    "cover_reference_dir": "用户提供的封面参考目录",
    "image_provider": "用户选择的渠道"
  }
}
```

上例中的数量、模式、分辨率仅表示字段类型，不是默认值。
通过 stdin 将 JSON 交给 `python scripts/startup_gate.py confirm --output <本次独立确认文件绝对路径>`。必须使用本次任务独立的新文件名，父目录使用已存在的任务工作目录。工具校验完整性并以排他方式创建文件，不扫描产品素材、不联网。

随后运行 workflow_cli.py init，并加 `--startup-confirmation <同一确认文件>`，其他参数逐项对应 fields。工具在读取产品目录和创建批次之前核对确认及参数；缺失或不一致就阻断，不可修改脚本、伪造确认或直接调用底层函数绕过。

确认记录只能验证结构与参数一致性，不能独立证明文字来自真实用户；宿主必须保留对话来源。模型拥有任意文件/代码执行权限时，此检查不是不可绕过的权限系统。
