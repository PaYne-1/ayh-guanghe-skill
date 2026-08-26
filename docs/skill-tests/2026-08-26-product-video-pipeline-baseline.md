# product-video-pipeline 技能基线记录

日期：2026-08-26

## 无新技能包时的观察结果

仓库根目录原 `SKILL.md` 是旧版爱优护专用技能，无法满足已批准流程：

- 默认 10 秒并采用多分镜快切，而新规范固定 15 秒、唯一分镜、一镜到底；
- 默认旧 ComfyUI 工作流和 1080P，而新规范使用 AutoDL.Art MiniMax-H3 V2、默认 768P、启动时可选 2K；
- 写死历史价格、产品素材路径和旧输出路径，不能让 WorkBuddy/Hermes 接收任意产品文件夹；
- 折叠过程、转弯和环绕镜头与新提示词限制冲突；
- 没有任务开始前统一确认、产品独立卖点库、批量验收报告或一次重跑学习协议。

## RED 证据

在创建 `skill-package/product-video-pipeline/` 前运行：

```text
python -m pytest tests/test_portable_skill_package.py -v
```

结果为 6 项失败：入口、资源结构、批次初始化、内容校验、AutoDL dry-run 和批量验收报告均不存在。Windows 编码回归阶段又新增两项测试，分别稳定复现子进程 GBK/UTF-8 解码失败和中文封面标题命令行传递失败。

## 成功条件

同一技能目录能被 Codex、WorkBuddy、Hermes 读取；无需付费调用即可完成自检；所有确定性工作流测试通过；正式 AutoDL 提交仍需要启动确认和显式付费授权。
