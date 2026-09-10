# 跨 Agent 安装和调用

整个 `product-video-pipeline` 文件夹就是技能包。不要只复制 `SKILL.md`，否则会缺少规则、配置和脚本。

## 通用安装

把文件夹放进目标智能体能扫描的 skills 目录；如果平台使用插件结构，则放到插件的 `skills/product-video-pipeline/`。重新加载技能列表后，通过自然语言或技能名调用。

## Codex

可复制到以下任一目录：

```text
~/.codex/skills/product-video-pipeline/
~/.agents/skills/product-video-pipeline/
```

调用示例：

```text
$product-video-pipeline
产品文件夹：D:\产品\轻便侠218
卖点：操作简单、轻便折叠
生成数量：4
```

## Hermes

Windows Hermes 的本地技能通常按分类存放，可复制到：

```text
%LOCALAPPDATA%\hermes\skills\creative\product-video-pipeline\
```

也可以放入 Hermes 当前配置声明的自定义 skills 根目录。重新启动或刷新技能后，输入“用 product-video-pipeline 为这个产品生成光合视频”。

## WorkBuddy / CodeBuddy

WorkBuddy 技能同样使用带 YAML frontmatter 的 `SKILL.md`。导入个人技能时选择整个文件夹；制作插件时使用：

```text
插件根目录/
└─ skills/
   └─ product-video-pipeline/
      ├─ SKILL.md
      ├─ references/
      ├─ profiles/
      └─ scripts/
```

安装后可以使用 `/product-video-pipeline`，也可以让 AI 根据“产品视频、爱优护、电动轮椅、光合视频、AutoDL H3”等语义自动匹配。

## 其他 Agent

无法自动发现 Agent Skills 的平台，可以把 `SKILL.md` 作为系统/专家提示词加载，并保持相对目录结构，让 Agent 按需读取 references。脚本需要 Python 3.9+，真实视频技术检查还需要 PATH 中的 ffmpeg 和 ffprobe；首次使用运行：

```powershell
python -m pip install -r requirements.txt
python scripts/self_test.py
```

## 环境变量

第一次调用时先按启动确认单沟通。回复后读取安全环境配置，只有缺少密钥或真实鉴权失败才引导用户配置；付费提交前脚本再次预检密钥和鉴权格式。

```text
AUTODL_API_KEY=由安全凭据注入
AUTODL_AUTH_SCHEME=bearer 或 raw
```

- 不要让用户在聊天中粘贴完整 API Key；应通过系统环境变量、平台密钥管理或其他不会回显密钥的安全方式配置。
- 配置完成后先进行不联网、不扣费的 dry-run，再开始产品任务。
- API 已接入不等于允许付费；V01 在已批准且绑定的项目费用清单内自动提交，V02 单独批准。

DeepSeek 文本接口的 base_url、模型及密钥通过安全环境配置接入。生图渠道在每个批次启动时必须由用户从 `本机 Codex 界面`、`ChatGPT 网页端`、`第三方 API` 三项中明确选择；三项平级，不设默认值或固定顺序。前两项使用当前已登录会话，且禁止服务器端 OpenAI API 调用；`第三方 API` 使用启动确认单中封存的五项连接/计价字段：`api_name`、`base_url`、`model`、`api_key_env`、`unit_price_yuan`。用户只确认一个**本批次最高总预算**，运行器在内部拆分 V01 视频与图片台账；不要求也不接受独立图片批次预算。为第三方渠道设置的只是 `api_key_env` 指定的环境变量，例如在安全环境中设置该变量；绝不把真实凭据写入启动 JSON、配置文件、命令行、日志或聊天内容。渠道批准后批次内锁定，禁止自动切换。

需要永久配置或更换凭据时说 `配置api`，然后使用 `python scripts/api_config.py status` 查看遮罩状态，并通过 `python scripts/api_config.py configure --category autodl|image|text` 在交互式终端隐藏输入。配置保存到 Windows 当前用户环境变量；详见 [API 永久配置向导](api-configuration.md)。

## 权限与安全说明

- 文件读取：用户指定产品文件夹第一层、封面参考文件夹第一层、技能包配置与任务 JSON。
- 文件写入：产品文件夹的 `生成视频/`、技能包或用户指定 knowledge 目录。
- 网络访问：只有正式运行 `autodl_h3.py` 时访问启动确认单中核对过的 AutoDL.Art HTTPS 端点；dry-run 不联网。
- 凭据：只读取环境变量 `AUTODL_API_KEY`，输出和异常不打印密钥。
- 外部进程：`self_test.py` 只调用同一 Python 解释器；真实媒体技术检查由运行器调用 ffprobe 和 ffmpeg。
- 删除行为：脚本不做递归删除，不覆盖已有不同 task_id，不在提交状态不明时自动重提。
