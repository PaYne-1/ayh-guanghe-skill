# product-video-pipeline 1.8.3

支持通过对话配置 API，无需用户亲自在终端隐藏输入。助手提取连接 JSON、服务商、模型与价格，调用 `scripts/api_chat_config.py` 保存到 Windows 当前用户环境变量，并回读验证。

- 支持图片、文本两类一次配置；第三方连接不会自动覆盖 AutoDL。
- 只追问缺失参数；图片单价仍需实际正数。
- 域名自动补 HTTPS，不擅自补 `/v1`。
- 输出仅显示遮罩密钥；校验失败不写入，写入或回读失败回滚。
- 保留可选隐藏输入入口；不联网，不代表授权付费生成。
- 聊天与宿主工具记录可能包含输入密钥，不能承诺无日志痕迹。

安装使用本目录的 `product-video-pipeline-v1.8.3.zip`，或仓库 `skill-package/product-video-pipeline` 完整目录。不要安装仓库根目录的旧 `SKILL.md`，也不要把整个仓库放进 Hermes skills 扫描目录。

Hermes 默认活动路径：`C:/Users/Administrator/AppData/Local/hermes/skills/creative/product-video-pipeline`。更新时保留本地 data 与既有凭据，备份放到 skills 扫描目录之外。重新加载技能后，在新对话中说“配置API”并提供连接信息。

离线验证：`python scripts/test_api_chat_config.py` 与 `python scripts/self_test.py`。
