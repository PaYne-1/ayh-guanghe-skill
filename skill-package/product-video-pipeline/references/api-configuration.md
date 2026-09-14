# API 永久配置向导

## 触发与输入方式

用户说“配置api”（API 大小写不限）或在配置对话中发送连接信息时进入本向导。支持用户直接在聊天中提供密钥、服务商、URL 和模型；不再强制用户操作隐藏输入框，不要求用户复制命令去执行。隐藏输入仅作为用户主动选择的备选方式。

聊天输入会留在平台聊天记录中。助手不复述完整密钥，不将密钥写进技能、项目 JSON、报告或临时脚本。工具调用可能由宿主记录，不能承诺聊天配置无日志痕迹。

配置授权仅用于保存凭据，不授权生图、视频、dry-run 或任何付费请求。

## 对话流程

没有推荐、默认或预选项；用户已经明确指定的类别直接采用。

1. 首先运行当前技能目录内的 `python scripts/api_config.py prompt` 并展示其遮罩状态。失败必须报告“无法读取当前配置状态，永久配置未更改”，不可猜测为未配置。类别行：AutoDL.Art 视频 API / 第三方生图 API / 第三方文本生成 API。用户已指定类别或同时指定图片和文本时直接处理，不再让用户重复选类别。
2. 从用户当前消息提取连接 JSON（`newapi_channel_conn` 的 key、url）、服务商、图片模型、文本模型和单张价格。去除粘贴造成的 Markdown 包装；域名缺少协议时补 https://，不擅自添加 /v1。同一条连接信息配合两种模型表示图片和文本共用该第三方连接，不得据此覆盖 AutoDL。
3. 仅询问缺少的必填项。生图单价可选，不询问用户；未提供则保留已有价格或标记未核实，不默认为免费。已有参数不要重复索取。用户未提供新的密钥时允许复用该类别已保存的密钥。
4. 使用下述非交互入口直接完成保存。不要运行会等待 input/getpass 的旧 configure 命令，不要用 export 或给 JSON 写 status: configured 代替保存。
5. 保存函数会先校验所有请求类别，再统一写入 Windows 当前用户环境变量，并回读比较；失败回滚。只报告工具真实结果和遮罩密钥，注明“未联网验证”。新对话用正式状态工具读取，不靠聊天记忆判断。

## 非交互入口（首选）

### 中文多行消息直接输入

save_chat_configuration 同时接受原始中文多行字符串，无需用户改成 JSON。支持 AUTODL_API_KEY、AUTODL_AUTH_SCHEME、第三方生图 API、第三方生图 模型、第三方文本生成 API、第三方文本生成 模型，以及各类的“地址”“服务商”和可选的图片“单张价格”。支持中文冒号、Markdown 转义下划线和换行。

助手将用户消息直接作为字符串传入 save_chat_configuration；不要打印原文。第三方生图和文本共用一个地址和密钥，模型分别保存；支持“第三方 API”“第三方 API 地址”配合两种模型，也兼容分别填写生图和文本 API。两类同时出现时自动共享连接；显式提供的连接值冲突时不写入，要求澄清。AutoDL 独立保存，绝不将其密钥自动用作第三方密钥。用户指定的模型名称原样保存，不自动换模型。

未提供的地址、服务商、单价从同类别的永久配置读取。缺少服务商或地址时只询问对应字段；单价不询问、不阻断凭据保存，标记未核实。所有请求类别完整后一起保存；失败不会部分写入。只有密钥和模型但未曾保存服务商/地址时，需要补全连接；缺少价格不影响配置成功。实际计费仍由运行时预算检查处理，不能把未知价格算作零。配置完整不等于网络验证有效；第三方密钥和 AutoDL 密钥不得混用。

在 Hermes 的 Python 代码执行工具中调用当前技能 scripts/api_chat_config.py 的函数。以下示例仅使用占位符；实际调用中由助手把用户已提供的值放入 payload，无需再次索取或要求用户操作终端：

```python
import sys
import json
sys.path.insert(0, r"C:/Users/Administrator/AppData/Local/hermes/skills/creative/product-video-pipeline/scripts")
from api_chat_config import save_chat_configuration

payload = {
    "shared_third_party": True,
    "provider": "用户指定的服务商",
    "connection": {
        "_type": "newapi_channel_conn",
        "url": "https://example.com",
        "key": "<用户提供的密钥>"
    },
    "image": {"model": "用户指定的图片模型"},
    "text": {"model": "用户指定的文本模型"}
}
# 不打印 payload。捕获异常时不要打印异常原文或 traceback。
try:
    result = save_chat_configuration(payload)
except Exception as exc:
    from api_config import format_error
    result = {"error": format_error(exc)}
print(json.dumps(result, ensure_ascii=False, indent=2))
```

只配置一个类别时省略另一个类别。AutoDL 单独使用 `{"autodl":{"key":"<用户提供的密钥>","auth_scheme":"bearer"}}`，鉴权格式可为 bearer 或 raw。

代码工具必须能访问本机 Windows 当前用户注册表。若工具运行在隔离环境，使用本机进程的 stdin 传入同样 JSON，调用 `python <当前技能绝对路径>/scripts/api_chat_config.py`；不要通过 shell 字符串插值拼接密钥或把密钥放进命令行参数。两种工具都不可用时明确报告工具限制，不得伪报成功。

## 永久环境变量

- AutoDL：AUTODL_API_KEY、AUTODL_AUTH_SCHEME
- 图片：PRODUCT_VIDEO_IMAGE_API_PROVIDER、PRODUCT_VIDEO_IMAGE_API_BASE_URL、PRODUCT_VIDEO_IMAGE_API_MODEL、PRODUCT_VIDEO_IMAGE_API_KEY、PRODUCT_VIDEO_IMAGE_API_UNIT_PRICE_YUAN
- 文本：PRODUCT_VIDEO_TEXT_API_PROVIDER、PRODUCT_VIDEO_TEXT_API_BASE_URL、PRODUCT_VIDEO_TEXT_API_MODEL、PRODUCT_VIDEO_TEXT_API_KEY

密钥保存在 Windows 当前用户环境变量，跨对话共享。旧 IMAGE_API_KEY 和描述 JSON 不代表新版配置已完成。配置入口读取注册表并回读验证，不依赖当前终端继承的临时变量。

## 隐藏输入备选

仅用户主动要求隐藏输入时使用：
`python scripts/api_config.py configure --category image`（或 text、autodl）。
不能把它作为对话配置的前置条件。完整性、URL 格式和预算约束保持不变。无安全免费鉴权端点时，不调用生成接口验证 Key。
