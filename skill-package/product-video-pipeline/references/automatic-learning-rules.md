# 学习模式自动复盘与后续规避规则

## 目标与强制链路

本文件可以单独发送给 Codex、WorkBuddy、Hermes 或其他能读取 Agent Skill 并运行本技能脚本的智能体。

学习闭环固定为：

`用户反馈 → 自动复盘 → V02验证 → 自动升级正式规则 → 下次任务强制加载并执行`

自动学习不等于无条件记忆。首次反馈只形成候选经验；解决方案必须在本条唯一一次 V02 重跑中得到对应验证，才可以进入正式规则。学习模式验证通过后自动升级，不再额外询问用户是否保存。

## 不可绕过的边界

- 只处理与当前任务、当前候选或当前工作流有关的纠正、质疑、不通过原因和修改要求。
- 闲聊、无关问题和没有可执行纠正含义的消息不得进入知识库。
- 最终视频仍由用户人工验收，自动检查不能代替用户决定。
- 每条视频仍只允许 V02 一次付费重跑。
- `failed` 或 `inconclusive` 的候选不得升级正式规则。
- 自动模式只读取正式规则，不读取候选经验。
- 不保存标题库、脚本库或分镜库；只保存可复用的问题解决规则和产品卖点。
- API、余额、预算和付费授权仍按原流程执行，学习规则不能扩大授权范围。

## 知识目录

所有智能体必须使用启动确认单中的同一知识目录：

```text
知识目录/
├─ 产品卖点库/
├─ 候选经验/
├─ 正式规则/
└─ .learning-rules.lock
```

候选与正式规则必须使用原子写入和跨进程锁。不得直接编辑部分 JSON、静默清空损坏文件或覆盖历史证据。

## 一、捕获用户问题

### 触发条件

学习模式执行期间，出现以下任一情况必须记录：

- 用户指出内容、标题、脚本、人物或卖点错误；
- 用户指出分镜、产品结构、Logo、人物、构图或封面错误；
- 用户指出音频漏词、截断、音色、说话人或顺序错误；
- 用户指出视频切镜、动作、口型、构图漂移、对白或产品失真；
- 用户指出 API、轮询、下载或任务恢复方法错误；
- 用户给出明确的不通过原因或修改要求。

### 问题归类

每个问题必须归入最早需要返回修改的一个节点：

| node | 适用问题 |
|---|---|
| `content` | 卖点、痛点、人物、标题、脚本 |
| `storyboard` | 产品结构、Logo、人物、构图、场景 |
| `cover` | 封面底图、版式、标题呈现 |
| `audio` | 漏词、截断、音色、说话人、顺序 |
| `video` | 动作、口型、切镜、构图漂移、对白 |
| `api` | 参数、鉴权、请求格式、提交 |
| `polling` | 查询方法、状态、超时恢复 |
| `download` | 文件损坏、地址失效、原子落盘 |
| `review` | 模型能力边界或跨节点验收问题 |

一个反馈包含多个可独立验证的问题时，拆成多条候选经验。不得把多个不同根因压成一条空泛规则。

## 二、自动复盘内容

收到问题后，智能体必须保留用户原话，并自动形成以下七项：

1. `user_feedback`：用户原话，不改写；
2. `symptom`：可以观察或检查的失败表现；
3. `root_cause`：基于证据的根因；证据不足时写“未知，待 V02 验证”；
4. `solution`：本次 V02 执行的最小修改；
5. `prevention_rule`：下次任务在相关节点执行前可以直接执行的动作；
6. `validation_method`：本次如何判断方案解决了问题；
7. `validation_expected`：通过时必须观察到的结果。

禁止使用“注意质量”“避免出错”“优化一下”等无法执行和验证的总结。

## 三、记录候选经验

使用以下命令。中文长文本建议由调用环境安全传参；不得把密钥或账号凭据写入参数。

```powershell
python scripts/workflow_cli.py record-issue `
  --knowledge-dir "知识目录" `
  --batch "批次目录" `
  --video-id "V001" `
  --node "storyboard" `
  --feedback "用户原话" `
  --symptom "可观察失败表现" `
  --root-cause "基于证据的根因或：未知，待 V02 验证" `
  --solution "本次 V02 的最小修改" `
  --prevention-rule "下次执行前必须采取的动作" `
  --validation-method "对应验证方法" `
  --validation-expected "预期通过结果" `
  --evidence "相关候选文件" `
  --model "当前模型" `
  --channel "当前渠道"
```

`--evidence` 可以重复。命令输出候选经验 JSON 的绝对路径。

批量验收的失败项由 `record-review` 自动形成结构化候选。验收结果可以额外提供 `node`、`symptom`、`root_cause`、`solution`、`prevention_rule`、`validation_method`、`validation_expected`、`model` 和 `channel`；缺失时使用保守默认值，根因不得编造。

## 四、V02 应用与验证

候选形成后：

1. 把 `solution` 应用到本条唯一一次 V02 重跑；
2. 保存与该问题对应的自动检查证据；
3. 用户明确通过 V02 后，再判断该问题的 `validation_method` 是否满足；
4. 只有用户明确通过且对应检查通过时，结果才是 `passed`；
5. V02 仍出现该问题时使用 `failed`；
6. 视频整体通过但无法证明该问题已解决时使用 `inconclusive`。

开始唯一一次重跑前，必须通过受控命令把任务从 V01 切换为 V02：

```powershell
python scripts/workflow_cli.py start-rerun `
  --batch "批次目录" `
  --video-id "V001"
```

该命令只允许 `retry_count` 从 `0` 变为 `1`，同时创建 `V02_唯一一次重跑` 历史目录；再次调用必须失败。不得直接修改 JSON 绕过次数限制。

通过并自动升级：

```powershell
python scripts/workflow_cli.py validate-learning `
  --knowledge-dir "知识目录" `
  --batch "批次目录" `
  --video-id "V001" `
  --issue-id "issue_xxxxxxxxxxxxxxxx" `
  --result passed `
  --candidate "_工作文件/生成过程/视频候选.mp4"
```

验证失败：

```powershell
python scripts/workflow_cli.py validate-learning `
  --knowledge-dir "知识目录" `
  --batch "批次目录" `
  --video-id "V001" `
  --issue-id "issue_xxxxxxxxxxxxxxxx" `
  --result failed
```

无法归因：

```powershell
python scripts/workflow_cli.py validate-learning `
  --knowledge-dir "知识目录" `
  --batch "批次目录" `
  --video-id "V001" `
  --issue-id "issue_xxxxxxxxxxxxxxxx" `
  --result inconclusive
```

`passed` 必须绑定实际候选文件并记录 SHA-256。`failed` 和 `inconclusive` 不生成正式规则。

## 五、正式规则

正式规则必须包含：适用产品、节点、模型、渠道、触发条件、强制动作、验证检查、来源问题、来源批次、来源视频、通过候选 SHA-256、验证时间、版本、命中次数和最后命中时间。

规则状态：

- `active`：允许后续任务自动加载；
- `superseded`：已被同范围的新验证规则替代；
- `disabled`：保留历史但禁止自动加载。

新规则与旧规则范围相同但动作不同时，新规则验证通过后版本递增，旧规则标记 `superseded` 并记录替代者。不得删除旧规则或改写旧验证结果。

## 六、下次任务自动加载

每次初始化学习模式或自动模式时，脚本必须读取 `正式规则/` 中全部 `active` 规则。启动确认单必须记录：

- `formal_rules_library`：正式规则库路径；
- `matched_learning_rules`：本次匹配的规则 ID、节点和执行动作；
- 未匹配规则及排除原因由执行 Agent 在启动检查证据中记录。

匹配优先级：

1. 产品专属规则高于全局规则；
2. 节点、模型和渠道限定更精确的规则优先；
3. 同等范围内，较新且验证通过的规则优先；
4. `superseded` 和 `disabled` 永不加载；
5. 无法自动消解的冲突必须报告，不得静默选择。

## 七、节点执行前强制注入

进入每个节点前必须运行：

```powershell
python scripts/workflow_cli.py prepare-node-rules `
  --knowledge-dir "知识目录" `
  --batch "批次目录" `
  --video-id "V001" `
  --node "video" `
  --model "MiniMax-H3" `
  --channel "AutoDL.Art"
```

命令会把清单写入：

```text
_工作文件/任务状态/生效规则_<node>.json
```

智能体必须读取其中每条 `required_action`，把动作加入当前节点的提示词约束、检查单或确定性校验，然后才能执行该节点。只生成清单、只在启动确认单中展示规则或只口头说明“已学习”，都不算自动规避。

每次实际准备节点规则都会更新 `hit_count` 和 `last_hit_at`。并发执行必须通过知识库锁更新，不能丢失命中次数。

## 八、再次失败与能力边界

正式规则已命中但同类问题再次出现时：

1. 保留旧规则和本次命中证据；
2. 新建候选经验，说明旧规则为什么不足；
3. 新方案在 V02 验证成功后产生新版本；
4. 旧规则标记为 `superseded`；
5. 不得篡改旧规则的历史验证结论。

模型在合理表达和唯一一次重跑后仍无法稳定完成时，可以记录模型能力边界。能力边界规则必须限定模型和场景，强制动作应是改用稳定表达、切换已授权渠道或停止继续付费重试，不能只写“模型不行”。

## 九、异常处理

- 知识库 JSON 损坏：保留原文件并暂停当前批次创作提交，不得静默清空。
- 自动复盘生成失败：至少保存用户原话和证据并标记待人工归类，不得丢失反馈。
- 重复反馈：按产品、节点、视频、用户原话和症状去重，追加证据与重复事件。
- 未知 API 提交状态：按技术恢复处理，不得总结为创作规则。
- V02 没有对应验证证据：使用 `inconclusive`，不得因视频整体通过而推断规则有效。

## 完成检查

一次学习闭环只有在以下条件全部满足时完成：

1. 用户原话已经进入候选经验；
2. 自动复盘七项字段完整；
3. V02 使用了候选解决方案；
4. 对应验证结果已记录为 `passed`、`failed` 或 `inconclusive`；
5. 只有 `passed` 自动生成正式规则；
6. 下次任务启动时列出匹配规则；
7. 相关节点执行前生成并读取生效规则清单；
8. `required_action` 已真实应用并保留命中记录。
