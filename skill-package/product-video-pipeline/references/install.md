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

无法自动发现 Agent Skills 的平台，可以把 `SKILL.md` 作为系统/专家提示词加载，并保持相对目录结构，让 Agent 按需读取 references。脚本需要 Python 3.9+；首次使用运行：

```powershell
python -m pip install -r requirements.txt
python scripts/self_test.py
```

## 环境变量

```text
AUTODL_API_KEY=由安全凭据注入
AUTODL_AUTH_SCHEME=bearer 或 raw
```

文本和生图 API 的 base_url、模型及密钥环境变量在每次任务启动确认单中配置，不固定写入技能包。

## 权限与安全说明

- 文件读取：用户指定产品文件夹第一层、封面参考文件夹第一层、技能包配置与任务 JSON。
- 文件写入：产品文件夹的 `生成视频/`、技能包或用户指定 knowledge 目录。
- 网络访问：只有正式运行 `autodl_h3.py` 时访问启动确认单中核对过的 AutoDL.Art HTTPS 端点；dry-run 不联网。
- 凭据：只读取环境变量 `AUTODL_API_KEY`，输出和异常不打印密钥。
- 外部进程：`self_test.py` 只调用同一 Python 解释器；媒体技术验收可由 Agent 另行调用 ffprobe。
- 删除行为：脚本不做递归删除，不覆盖已有不同 task_id，不在提交状态不明时自动重提。
