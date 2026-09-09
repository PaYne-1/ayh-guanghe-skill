# Hermes 本地 Qwen 部署与 ayh-h3 集成设计

## 目标

在当前 Windows 电脑上部署本地 Qwen 推理服务，用它替换 Hermes Agent 当前使用的 DeepSeek 主模型，同时保持 `ayh-h3` / `product-video-pipeline` 技能包以及 AutoDL MiniMax H3 视频生成接口不变。部署必须允许 DeepSeek 与本地 Qwen 并存，并为以后迁移到租用或自购 Linux GPU 服务器保留稳定的 OpenAI 兼容接口。

## 当前条件

- 操作系统：Windows。
- CPU：Intel Core i7-13700，24 逻辑处理器。
- GPU：NVIDIA GeForce RTX 3060，12 GB 显存。
- 当前编排：Hermes Agent 使用 DeepSeek API 作为主推理模型。
- 视频流水线：Hermes 读取技能包并调用脚本，最终视频仍由 AutoDL MiniMax H3 服务生成。
- Hermes 要求本地工具型 Agent 使用至少 64K 上下文；模型服务的实际上下文必须与 Hermes 配置一致。

## 方案比较

### 方案 A：Ollama + Qwen3.5 9B（采用）

优点是 Windows 安装和模型管理简单，自动进行 GPU 卸载，提供 OpenAI 兼容接口，支持工具调用，并且以后可在服务器继续使用相同接口。缺点是 12 GB 显存下运行 64K 上下文较紧张，可能需要量化 KV Cache、部分 CPU 卸载或降低并发。

### 方案 B：LM Studio + Qwen

优点是图形界面直观，便于手动观察模型和显存。缺点是后台服务管理、自动启动和服务器迁移不如 Ollama 一致。

### 方案 C：WSL2 + vLLM

优点是最接近后期 Linux 服务器生产部署。缺点是当前 12 GB 显存余量有限，Windows/WSL2 网络和 CUDA 配置更复杂，不适合作为第一阶段验证方案。

## 总体架构

```text
Hermes Agent
  ├─ 主选：local-qwen（OpenAI 兼容接口）
  ├─ 回退：现有 DeepSeek 提供商
  └─ 技能：product-video-pipeline / ayh-h3
       └─ AutoDL MiniMax H3（视频生成，保持不变）

本机阶段：Hermes → 127.0.0.1:<已登记 AI 服务端口>/v1 → Ollama → Qwen
服务器阶段：Hermes → 服务器 HTTPS 地址/v1 → vLLM 或 Ollama → 更大 Qwen
```

## 项目与端口

实施时新建独立项目：`D:\0-AI 项目\本地Qwen推理服务`，技术内部标识为 `local-qwen-service`。

创建项目之前读取 `C:\Users\Administrator\.codex\PORT_REGISTRY.json`，从 AI/自动化服务范围 `7001-7199` 中选择最小的未登记且未被系统占用的端口，立即登记。不得假设端口一定为 7001。Ollama 监听地址固定为 `127.0.0.1:<分配端口>`，Hermes 的 Base URL 固定为 `http://127.0.0.1:<分配端口>/v1`。

项目根目录生成 `PROJECT_INFO.md`，记录项目路径、技术标识、固定端口、启动命令和本地访问地址。

## 模型配置

第一候选模型为 Ollama 官方仓库中的 `qwen3.5:9b` 量化版本。选择它是因为它能在 RTX 3060 12 GB 上进行可用性验证，同时支持中文、工具调用和图片输入。若实测模型标签或硬件兼容性发生变化，以安装时 Ollama 官方可用标签为准，但不得未经记录切换到第三方非官方模型。

服务端实际上下文设置为 64K；Hermes 的 `context_length` 同样设置为 65536。启用 Flash Attention，并优先使用量化 KV Cache，以降低长上下文显存占用。服务并发固定为 1，避免 12 GB 显存上出现并发上下文挤占。

如果 64K 启动失败或持续发生显存不足，不把 Hermes 配置伪装成 64K，也不直接降低到 Hermes 不接受的上下文。应保留诊断证据，然后依次尝试：更激进的官方量化、更多 CPU 卸载、较小且支持工具调用的官方 Qwen，最后才建议使用云端或服务器模型。

## Hermes 配置

Hermes 使用 `custom` 提供商接入本地服务，而不是覆盖 DeepSeek 的现有凭据。配置包含：

- 提供商：`custom`。
- 命名端点：`local-qwen`。
- Base URL：本机 OpenAI 兼容 `/v1` 地址。
- 模型名：Ollama 实际加载的 Qwen 标签。
- API Key：本机环回地址无需真实密钥；如 Hermes 字段必填，使用仅用于本机的非敏感占位值。
- 上下文：65536。
- 原生图片输入：模型与服务验证支持后才设置 `supports_vision: true`。

现有 DeepSeek 配置和密钥不得删除、移动或打印。Qwen 验证期间通过 Hermes 的模型切换功能选择 `local-qwen`；DeepSeek 保持可切回，并配置为失败回退路径。

## 数据流

1. 用户在 Hermes 中提出产品视频任务。
2. Hermes 把系统提示、技能说明和用户输入发送给本机 Qwen。
3. Qwen 生成结构化工具调用，Hermes 执行技能包内脚本。
4. 在验证阶段，只运行本地校验或 AutoDL dry-run，不进行付费提交。
5. 正式业务阶段仍由 AutoDL MiniMax H3 生成视频，Qwen 不承担视频扩散或渲染。

## 安全边界

- 推理服务默认只绑定 `127.0.0.1`，不向局域网或公网开放。
- DeepSeek、AutoDL 等 API Key 保持在现有安全配置中，不写入仓库、日志、设计文档或聊天输出。
- 后期服务器部署必须使用 HTTPS、访问控制和防火墙；不得直接把无鉴权推理端口暴露到公网。
- 部署和测试不触发 AutoDL 付费调用；正式付费提交仍遵守技能包现有确认规则。

## 错误处理与回退

- 本机服务未启动或连接失败：Hermes 回退 DeepSeek，并明确记录本地端点不可用。
- 模型把工具调用当普通文本输出：确认模型原生工具支持和 Ollama 工具调用路径，测试失败则不晋升为默认模型。
- 上下文不足：核对 Ollama 实际上下文和 Hermes 启动报告，不依赖模型标称最大值。
- 显存不足：采集启动日志与显存状态，按模型配置章节中的顺序降级。
- Qwen 输出不满足技能契约：保留 DeepSeek 为生产默认，Qwen 继续作为测试模型，不修改视频流水线规则绕过模型缺陷。

## 验证方案

验证分四层进行：

1. 服务健康检查：OpenAI 兼容 `/v1/models` 和 `/v1/chat/completions` 可响应。
2. 模型能力检查：中文指令、长上下文、JSON/结构化输出、工具调用和图片输入分别测试。
3. Hermes 集成检查：Hermes 能选择 `local-qwen`、显示正确上下文，并执行一个无副作用的工具调用。
4. `ayh-h3` 回归检查：使用固定测试输入执行技能启动理解、内容规划和 dry-run；不得联网提交付费视频。将 Qwen 与 DeepSeek 的结果按规则遵循、字段完整性、工具调用成功率和耗时进行对比。

只有连续多次完成工具调用、无关键技能规则遗漏且 dry-run 通过，才能把 Qwen 设为 Hermes 默认主模型。否则保持 DeepSeek 为默认、本地 Qwen 为可选测试模型。

## 服务器迁移

迁移时保持 Hermes、技能包和 AutoDL 接口不变。服务器侧可以根据 GPU 选择 vLLM 或 Ollama，并加载更大的 Qwen 模型。迁移步骤只涉及部署新的 OpenAI 兼容端点、建立 HTTPS/鉴权、完成相同验收测试，以及把 Hermes 的 `local-qwen` Base URL 改为服务器地址。

## 完成标准

- 本机 Qwen 服务能稳定启动，并固定使用已登记端口。
- Hermes 可在 DeepSeek 与 `local-qwen` 之间切换，DeepSeek 配置未受破坏。
- Hermes 识别至少 64K 实际上下文。
- Qwen 能正确触发工具调用，而不是输出伪工具调用文本。
- `ayh-h3` 固定用例的非付费 dry-run 通过。
- 项目包含可复现的启动、停止、健康检查和迁移说明。
- 未发生任何 AutoDL 付费提交，未泄露任何 API Key。
