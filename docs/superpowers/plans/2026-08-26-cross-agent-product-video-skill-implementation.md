# 跨 Agent 产品视频技能包实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 将现有 ayh-h3 脚本升级为跨 Codex、WorkBuddy、Hermes 和通用 Agent 的产品视频技能包，完整实现已批准的 11 节点流水线、批量验收和经验学习。

**Architecture:** 使用 product_video_skill Python 包保存唯一业务逻辑，以原子 JSON 状态机驱动每条视频。Agent 原生文本/生图能力通过待办动作协议接入，AutoDL.Art MiniMax-H3 由 Python 直接调用，本地验收页通过轻量 HTTP 服务回写批次结果。

**Tech Stack:** Python 3.9、dataclasses、requests、Pillow、pytest、标准库 http.server、ffprobe/ffmpeg、HTML/CSS/JavaScript、Markdown/JSON。

## Global Constraints

- 项目根目录固定为 D:\0-AI 项目\ayh-h3。
- 产品图片路径由用户每次提供，只读取第一层图片，不递归。
- 一条视频只使用一个核心痛点和一个卖点。
- 每条视频固定 15 秒、9:16；默认 768P，任务启动时可选 2K。
- 生视频固定使用 https://www.autodl.art/api/v1/minimax/v2/video_generation 的 MiniMax-H3。
- 分镜图每条最终 1 张，最多尝试 3 次；视频每条最多重跑 1 次。
- 默认并发数 3，默认轮询间隔 20 秒，单条连续等待上限 60 分钟，下载最多重试 4 次。
- 默认关闭 AIGC 画面水印，不生成背景音乐。
- 视频发布标题约 20 个汉字且必须包含“电动轮椅”；封面标题 4 至 6 个汉字。
- 发布正文 80 至 150 个汉字，固定话题标签不计入字数。
- 脚本、标题、分镜和提示词只保存在任务项目中，不沉淀为脚本分镜库。
- 新经验先进入候选库，学习模式下经用户确认且验证有效后才能成为正式规则。
- API 密钥只能来自环境变量或安全凭据，不得写入仓库、日志或任务输出。
- 所有代码改动先写失败测试，再实现，再运行验证，再提交。

---

## 文件结构锁定

新增核心包：

    product_video_skill/
    ├─ __init__.py
    ├─ cli.py
    ├─ models.py
    ├─ config.py
    ├─ storage.py
    ├─ state_machine.py
    ├─ allocation.py
    ├─ product.py
    ├─ registry.py
    ├─ actions.py
    ├─ versioning.py
    ├─ workflow.py
    ├─ validation/
    │  ├─ __init__.py
    │  ├─ content.py
    │  ├─ image.py
    │  └─ video.py
    ├─ providers/
    │  ├─ __init__.py
    │  ├─ text.py
    │  ├─ image.py
    │  └─ autodl_h3.py
    ├─ media/
    │  ├─ __init__.py
    │  ├─ cover.py
    │  ├─ download.py
    │  └─ probe.py
    ├─ review/
    │  ├─ __init__.py
    │  ├─ auto_qa.py
    │  ├─ server.py
    │  ├─ results.py
    │  └─ templates/
    │     └─ batch_review.html
    └─ learning/
       ├─ __init__.py
       ├─ repository.py
       └─ retrospective.py

新增配置与规则：

    profiles/爱优护电动轮椅_淘宝天猫光合.json
    rules/common/content.md
    rules/common/consistency.md
    rules/electric_wheelchair/motion.md
    rules/electric_wheelchair/folding.md
    rules/profiles/ayh_guanghe.md
    data/产品卖点库/.gitkeep
    data/候选经验/.gitkeep
    data/正式经验/.gitkeep
    data/模型能力边界/.gitkeep
    封面图参考/.gitkeep

新增测试：

    tests/
    ├─ test_models.py
    ├─ test_state_machine.py
    ├─ test_product_and_allocation.py
    ├─ test_actions_and_config.py
    ├─ test_content_pipeline.py
    ├─ test_image_and_cover_pipeline.py
    ├─ test_autodl_h3.py
    ├─ test_scheduler_and_budget.py
    ├─ test_poll_and_download.py
    ├─ test_execution_pipeline.py
    ├─ test_review_server.py
    ├─ test_learning.py
    └─ test_end_to_end.py

保留现有 scripts/h3_gen.py 作为旧版兼容入口；新代码不得继续依赖旧 ComfyUI 提交协议。

---

## 里程碑一：基础模型、状态与启动配置

### Task 1: 建立 Python 包和领域模型

**Files:**
- Create: pyproject.toml
- Create: product_video_skill/__init__.py
- Create: product_video_skill/models.py
- Test: tests/test_models.py

**Interfaces:**
- Produces: RunMode、VideoState、BatchConfig、VideoRecord、ActionRequest、ReviewDecision。
- Consumes: 无。

- [ ] **Step 1: 写领域模型失败测试**

    from decimal import Decimal
    from pathlib import Path
    from product_video_skill.models import BatchConfig, RunMode, VideoRecord, VideoState

    def test_batch_config_and_record_round_trip(tmp_path: Path):
        config = BatchConfig(
            product_dir=tmp_path,
            product_name="爱优护轻便侠218",
            run_mode=RunMode.LEARNING,
            total_videos=5,
            selling_points=("轻便", "操作简单"),
            resolution="768P",
            duration=15,
            ratio="9:16",
            concurrency=3,
            max_budget_yuan=Decimal("100"),
        )
        record = VideoRecord.create("V001", "轻便", tmp_path / "V001")
        assert config.duration == 15
        assert record.state is VideoState.CREATED
        assert VideoRecord.from_dict(record.to_dict()) == record

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_models.py -v
Expected: FAIL，提示 product_video_skill.models 不存在。

- [ ] **Step 3: 创建包配置和领域模型**

pyproject.toml 至少包含：

    [build-system]
    requires = ["setuptools>=68"]
    build-backend = "setuptools.build_meta"

    [project]
    name = "cross-agent-product-video-skill"
    version = "0.1.0"
    requires-python = ">=3.9"
    dependencies = [
      "requests>=2.31,<3",
      "Pillow>=10.4,<13",
    ]

    [project.optional-dependencies]
    test = ["pytest>=8,<9"]

    [project.scripts]
    product-video-skill = "product_video_skill.cli:main"

models.py 实现 str Enum 和 dataclass。BatchConfig.max_budget_yuan 固定使用 Decimal。VideoRecord 是可变 dataclass，并明确包含 item_id、selling_point、project_dir、state、task_id、request_id、request_hash、request_payload、retry_count、estimated_cost_yuan、actual_cost_yuan、blocked_reason、created_at、updated_at；不得依赖运行时临时加字段。VideoRecord 必须提供：

    @classmethod
    def create(cls, item_id: str, selling_point: str, project_dir: Path) -> "VideoRecord"

    def to_dict(self) -> dict

    @classmethod
    def from_dict(cls, value: dict) -> "VideoRecord"

所有 Path 序列化为绝对字符串，枚举序列化为 value。

- [ ] **Step 4: 运行领域模型测试**

Run: python -m pytest tests/test_models.py -v
Expected: 1 passed。

- [ ] **Step 5: 提交**

    git add pyproject.toml product_video_skill/__init__.py product_video_skill/models.py tests/test_models.py
    git commit -m "feat: add product video domain models"

### Task 2: 原子存储和状态机

**Files:**
- Create: product_video_skill/storage.py
- Create: product_video_skill/state_machine.py
- Test: tests/test_state_machine.py

**Interfaces:**
- Consumes: VideoRecord、VideoState。
- Produces: atomic_write_json(path, value)、BatchStore、transition(record, target)。

- [ ] **Step 1: 写状态机失败测试**

    import pytest
    from product_video_skill.models import VideoRecord, VideoState
    from product_video_skill.state_machine import InvalidTransition, transition
    from product_video_skill.storage import BatchStore

    def test_state_transition_is_atomic(tmp_path):
        record = VideoRecord.create("V001", "轻便", tmp_path / "V001")
        store = BatchStore(tmp_path)
        store.save_video(record)
        updated = transition(record, VideoState.CONTENT_READY)
        store.save_video(updated)
        assert store.load_video("V001").state is VideoState.CONTENT_READY
        assert not (tmp_path / "V001" / "任务信息.json.tmp").exists()

    def test_illegal_transition_is_rejected(tmp_path):
        record = VideoRecord.create("V001", "轻便", tmp_path / "V001")
        with pytest.raises(InvalidTransition):
            transition(record, VideoState.PASSED)

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_state_machine.py -v
Expected: FAIL，提示 storage 或 state_machine 模块不存在。

- [ ] **Step 3: 实现存储和显式状态图**

storage.py 必须使用同目录临时文件后 Path.replace：

    def atomic_write_json(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

state_machine.py 使用以下状态图，不允许跳过付费边界：

    ALLOWED_TRANSITIONS = {
        VideoState.CREATED: {VideoState.CONTENT_READY, VideoState.MANUAL_REQUIRED},
        VideoState.CONTENT_READY: {
            VideoState.CONTENT_REVIEW,
            VideoState.STORYBOARD_READY,
            VideoState.MANUAL_REQUIRED,
        },
        VideoState.CONTENT_REVIEW: {
            VideoState.CONTENT_READY,
            VideoState.STORYBOARD_READY,
            VideoState.MANUAL_REQUIRED,
        },
        VideoState.STORYBOARD_READY: {
            VideoState.IMAGE_REVIEW,
            VideoState.COVER_READY,
            VideoState.MANUAL_REQUIRED,
        },
        VideoState.IMAGE_REVIEW: {
            VideoState.STORYBOARD_READY,
            VideoState.COVER_READY,
            VideoState.MANUAL_REQUIRED,
        },
        VideoState.COVER_READY: {VideoState.COPY_READY, VideoState.MANUAL_REQUIRED},
        VideoState.COPY_READY: {VideoState.READY_TO_SUBMIT, VideoState.MANUAL_REQUIRED},
        VideoState.READY_TO_SUBMIT: {VideoState.SUBMITTING, VideoState.MANUAL_REQUIRED},
        VideoState.SUBMITTING: {
            VideoState.SUBMITTED,
            VideoState.SUBMIT_UNKNOWN,
            VideoState.MANUAL_REQUIRED,
        },
        VideoState.SUBMIT_UNKNOWN: {VideoState.SUBMITTED, VideoState.MANUAL_REQUIRED},
        VideoState.SUBMITTED: {VideoState.POLLING},
        VideoState.POLLING: {
            VideoState.DOWNLOADED,
            VideoState.POLL_TIMEOUT,
            VideoState.MANUAL_REQUIRED,
        },
        VideoState.POLL_TIMEOUT: {VideoState.POLLING, VideoState.MANUAL_REQUIRED},
        VideoState.DOWNLOADED: {VideoState.AWAITING_REVIEW},
        VideoState.AWAITING_REVIEW: {
            VideoState.PASSED,
            VideoState.RETRY_PENDING,
            VideoState.MANUAL_REQUIRED,
        },
        VideoState.RETRY_PENDING: {
            VideoState.CONTENT_READY,
            VideoState.STORYBOARD_READY,
            VideoState.COPY_READY,
            VideoState.READY_TO_SUBMIT,
            VideoState.MANUAL_REQUIRED,
        },
        VideoState.PASSED: set(),
        VideoState.MANUAL_REQUIRED: set(),
    }

- [ ] **Step 4: 运行测试**

Run: python -m pytest tests/test_state_machine.py -v
Expected: 2 passed。

- [ ] **Step 5: 提交**

    git add product_video_skill/storage.py product_video_skill/state_machine.py tests/test_state_machine.py
    git commit -m "feat: add resumable video state machine"

### Task 3: 产品扫描、数量分配和目录布局

**Files:**
- Create: product_video_skill/product.py
- Create: product_video_skill/allocation.py
- Create: product_video_skill/registry.py
- Test: tests/test_product_and_allocation.py

**Interfaces:**
- Produces: scan_product_images(product_dir) -> tuple[Path, ...]、infer_product_name(product_dir) -> str、allocate_videos(points, total) -> dict[str, int]、create_batch_layout(config, timestamp) -> Path、SellingPointLibrary.record(product_name, product_path, points, used_at) -> ProductSellingPoints。

- [ ] **Step 1: 写扫描和分配失败测试**

    from PIL import Image
    from product_video_skill.allocation import allocate_videos
    from product_video_skill.product import infer_product_name, scan_product_images

    def test_scan_only_reads_first_level_images(tmp_path):
        product = tmp_path / "测试产品"
        product.mkdir()
        Image.new("RGB", (64, 64)).save(product / "a.png")
        (product / "nested").mkdir()
        Image.new("RGB", (64, 64)).save(product / "nested" / "b.png")
        assert [path.name for path in scan_product_images(product)] == ["a.png"]
        assert infer_product_name(product) == "测试产品"

    def test_allocation_spreads_remainder_from_front():
        points = ("A", "B", "C", "D", "E")
        assert allocate_videos(points, 23) == {"A": 5, "B": 5, "C": 5, "D": 4, "E": 4}

    def test_selling_points_are_deduplicated_and_isolated_by_product(tmp_path):
        from datetime import datetime, timezone
        from product_video_skill.registry import SellingPointLibrary

        library = SellingPointLibrary(tmp_path / "data" / "产品卖点库")
        now = datetime(2026, 8, 26, tzinfo=timezone.utc)
        library.record("产品甲", tmp_path / "产品甲", ("轻便", "轻便"), now)
        library.record("产品乙", tmp_path / "产品乙", ("操作简单",), now)
        library.record("产品甲", tmp_path / "产品甲", ("轻便",), now)
        assert library.load("产品甲").points[0].use_count == 2
        assert [point.content for point in library.load("产品乙").points] == ["操作简单"]

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_product_and_allocation.py -v
Expected: FAIL，提示目标模块不存在。

- [ ] **Step 3: 实现扫描、分配和批次目录**

scan_product_images 只接受 .png、.jpg、.jpeg、.webp，按文件名稳定排序，忽略全部目录和 `生成视频`。create_batch_layout 创建：

    产品目录/生成视频/YYYYMMDD_批次NNN/

单条目录名使用 V001_卖点关键词_封面标题；Windows 非法字符统一替换为下划线。

SellingPointLibrary 在 `data/产品卖点库/{产品内部标识}.json` 中按产品独立存储产品名称、内部标识、最近产品路径、卖点分类、卖点内容、首次使用时间、最近使用时间和使用次数。内容相同的卖点去重并增加使用次数；不同产品绝不共用同一记录。它只沉淀卖点，不保存标题、脚本、分镜或提示词。

- [ ] **Step 4: 运行测试**

Run: python -m pytest tests/test_product_and_allocation.py -v
Expected: 3 passed。

- [ ] **Step 5: 提交**

    git add product_video_skill/product.py product_video_skill/allocation.py product_video_skill/registry.py tests/test_product_and_allocation.py
    git commit -m "feat: add product discovery and batch layout"

### Task 4: 启动确认单、配置校验和 Agent 动作协议

**Files:**
- Create: product_video_skill/config.py
- Create: product_video_skill/actions.py
- Create: product_video_skill/cli.py
- Test: tests/test_actions_and_config.py

**Interfaces:**
- Produces: validate_preflight(config) -> list[str]、requires_manual_review(mode, stage) -> bool、ActionBroker.request(kind, payload) -> ActionRequest、ActionBroker.complete(action_id, result) -> None、CLI init/resume/status。

- [ ] **Step 1: 写启动配置和动作协议失败测试**

    from dataclasses import replace
    from decimal import Decimal
    from pathlib import Path
    from PIL import Image
    from product_video_skill.actions import ActionBroker
    from product_video_skill.config import requires_manual_review, validate_preflight
    from product_video_skill.models import BatchConfig, RunMode

    def test_preflight_requires_budget_and_models(tmp_path):
        product = tmp_path / "测试产品"
        product.mkdir()
        Image.new("RGB", (64, 64), "white").save(product / "a.png")
        config = BatchConfig(
            product_dir=product,
            product_name="测试产品",
            run_mode=RunMode.LEARNING,
            total_videos=1,
            selling_points=("操作简单",),
            resolution="768P",
            duration=15,
            ratio="9:16",
            concurrency=3,
            max_budget_yuan=Decimal("10"),
        )
        broken = replace(config, max_budget_yuan=Decimal("0"))
        assert "本批次最高预算必须大于 0" in validate_preflight(broken)

    def test_native_action_survives_restart(tmp_path):
        broker = ActionBroker(tmp_path / "actions")
        request = broker.request("image_generation", {"prompt": "真实手机实拍"})
        reloaded = ActionBroker(tmp_path / "actions").get(request.action_id)
        assert reloaded.status == "pending"

    def test_review_gates_follow_selected_mode_but_final_video_is_always_manual():
        assert requires_manual_review(RunMode.LEARNING, "content") is True
        assert requires_manual_review(RunMode.LEARNING, "storyboard") is True
        assert requires_manual_review(RunMode.AUTO, "content") is False
        assert requires_manual_review(RunMode.AUTO, "storyboard") is False
        assert requires_manual_review(RunMode.AUTO, "final_video") is True

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_actions_and_config.py -v
Expected: FAIL，提示 config 或 actions 不存在。

- [ ] **Step 3: 实现一次性启动确认和动作协议**

validate_preflight 必须检查产品图片、封面参考库、运行模式、文本能力、生图能力、AutoDL 凭据、15 秒、9:16、768P/2K、并发、预算和重试上限。所有配置一次写入 `启动确认单.json` 并由用户在批次开始前确认；运行中不得临时追问模型、API、分辨率、配音或普通预算参数。

requires_manual_review 在学习模式对 content 和 storyboard 返回 True，在自动模式返回 False；final_video 在两种模式下都返回 True。自动模式仅在内容校验和图片 QA 通过时跳过前置人工门，失败项目仍按隔离规则处理。

ActionBroker 把 Agent 原生任务写为：

    actions/pending/{action_id}.json

完成后移动为：

    actions/completed/{action_id}.json

CLI 提供：

    product-video-skill init --config 启动确认单.json
    product-video-skill status --batch 批次路径
    product-video-skill next-actions --batch 批次路径
    product-video-skill complete-action --batch 批次路径 --action 动作ID --result 结果路径
    product-video-skill resume --batch 批次路径

- [ ] **Step 4: 运行测试和 CLI 帮助**

Run: python -m pytest tests/test_actions_and_config.py -v
Expected: 3 passed。

Run: python -m product_video_skill.cli --help
Expected: 显示 init、status、next-actions、complete-action、resume。

- [ ] **Step 5: 提交**

    git add product_video_skill/config.py product_video_skill/actions.py product_video_skill/cli.py tests/test_actions_and_config.py
    git commit -m "feat: add preflight and native agent action protocol"

---

## 里程碑二：内容、分镜和封面流水线

### Task 5: 产品配置和模块化规则

**Files:**
- Create: profiles/爱优护电动轮椅_淘宝天猫光合.json
- Create: rules/common/content.md
- Create: rules/common/consistency.md
- Create: rules/electric_wheelchair/motion.md
- Create: rules/electric_wheelchair/folding.md
- Create: rules/profiles/ayh_guanghe.md
- Modify: product_video_skill/config.py
- Test: tests/test_content_pipeline.py

**Interfaces:**
- Produces: ProductProfile.load(path) -> ProductProfile、render_rule_bundle(profile, task) -> str。

- [ ] **Step 1: 写配置规则失败测试**

    def test_ayh_profile_contains_confirmed_copy_rules():
        profile = ProductProfile.load(Path("profiles/爱优护电动轮椅_淘宝天猫光合.json"))
        assert profile.required_title_term == "电动轮椅"
        assert profile.publish_title_count == 1
        assert profile.publish_title_target_chars == 20
        assert profile.publish_title_style == "标题党但语义顺畅且不夸张"
        assert profile.closing_product_name == "爱优护电动轮椅"
        assert profile.fixed_hashtags == (
            "#爱优护电动轮椅",
            "#ainsnbot高端智能电动轮椅",
            "#电动轮椅",
            "#老人专用电动轮椅",
        )

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_content_pipeline.py::test_ayh_profile_contains_confirmed_copy_rules -v
Expected: FAIL，提示 ProductProfile 或配置文件不存在。

- [ ] **Step 3: 写产品配置和规则文件**

JSON 必须包含 product_name、category、platform、required_title_term、publish_title_count、publish_title_target_chars、publish_title_style、closing_product_name、fixed_hashtags、duration、ratio、body_min_chars、body_max_chars、cover_title_min_chars、cover_title_max_chars 和 rule_files。首个爱优护配置把标题数量固定为 1、目标约 20 个汉字、风格设为“标题党但语义顺畅且不夸张”；仅强制包含“电动轮椅”，不强制包含品牌词。

规则文件必须逐条落实设计规范第 9 节的单卖点、人物一致性、15 秒三段节奏、无字幕、直线运动和折叠限制。不得把爱优护规则写进 common 文件。

- [ ] **Step 4: 运行配置测试**

Run: python -m pytest tests/test_content_pipeline.py::test_ayh_profile_contains_confirmed_copy_rules -v
Expected: PASS。

- [ ] **Step 5: 提交**

    git add profiles rules product_video_skill/config.py tests/test_content_pipeline.py
    git commit -m "feat: add modular wheelchair content profile"

### Task 6: 内容生成契约和严格校验

**Files:**
- Create: product_video_skill/providers/text.py
- Create: product_video_skill/validation/__init__.py
- Create: product_video_skill/validation/content.py
- Create: product_video_skill/workflow.py
- Create: tests/fixtures/valid_content.json
- Modify: tests/test_content_pipeline.py

**Interfaces:**
- Produces: ContentPackage、ContentGenerator.generate(input) -> ContentPackage、validate_content(package, profile) -> list[ValidationIssue]。
- Consumes: ActionBroker、ProductProfile、VideoRecord。

- [ ] **Step 1: 写内容校验失败测试**

    from pathlib import Path
    import pytest
    from product_video_skill.config import ProductProfile
    from product_video_skill.providers.text import ContentPackage
    from product_video_skill.validation.content import validate_content

    @pytest.fixture
    def ayh_profile():
        return ProductProfile.load(Path("profiles/爱优护电动轮椅_淘宝天猫光合.json"))

    def content_package(**changes):
        value = {
            "video_id": "V001",
            "selling_point": "操作简单",
            "core_idea": "家属询问老人是否会操作",
            "audience": "老人和家属",
            "scene": "小区步道",
            "pain_point": "老人担心不会操作",
            "angle": "老人真实使用回答",
            "topic": "爸妈能不能自己操作",
            "publish_title": "爸妈也能上手的电动轮椅到底怎么样",
            "cover_title": "爸妈会操作",
            "people": [
                {"id": "P1", "identity": "老人", "gender": "女", "age_feel": "70岁左右", "position": "画面左侧坐在轮椅上", "action": "手放控制器上", "speaks": True},
                {"id": "P2", "identity": "家属", "gender": "女", "age_feel": "40岁左右", "position": "轮椅右侧", "action": "自然侧身提问", "speaks": True},
            ],
            "closing_speaker_id": "P1",
            "script_segments": [
                {"start": 0, "end": 4, "speaker_id": "P2", "dialogue": "这个操作会不会很难？"},
                {"start": 4, "end": 11, "speaker_id": "P1", "dialogue": "操作很顺手，我自己就能开，家里人也省心。"},
                {"start": 11, "end": 15, "speaker_id": "P1", "dialogue": "用了爱优护电动轮椅后，出门更方便，可以了解一下。"},
            ],
            "storyboard_prompt": "画面中共有两位女性，老人和家属同框。",
            "storyboard_people": ["P1", "P2"],
            "video_prompt": "固定镜头，轮椅直线缓慢前进，两位女性始终同框。",
            "final_feeling": "真实生活分享",
            "filming_advice": "固定正侧45度角拍摄",
            "duration": 15,
        }
        value.update(changes)
        return ContentPackage.from_dict(value)

    def test_content_validator_rejects_wrong_people_and_missing_title_term(ayh_profile):
        package = content_package(
            publish_title="爸妈出门方便多了",
            people=[
                {"id": "P1", "identity": "老人", "gender": "女", "age_feel": "70岁左右", "position": "画面左侧", "action": "坐在轮椅上", "speaks": True},
                {"id": "P2", "identity": "家属", "gender": "女", "age_feel": "40岁左右", "position": "轮椅右侧", "action": "自然提问", "speaks": True},
            ],
            storyboard_people=["老人"],
        )
        codes = {issue.code for issue in validate_content(package, ayh_profile)}
        assert codes == {"title.required_term", "people.count_mismatch"}

    def test_wheelchair_motion_validator_rejects_turning(ayh_profile):
        package = content_package(video_prompt="老人驾驶轮椅转弯进入电梯")
        codes = {issue.code for issue in validate_content(package, ayh_profile)}
        assert "wheelchair.turning_forbidden" in codes

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_content_pipeline.py -v
Expected: FAIL，提示 ContentPackage 或 validate_content 不存在。

- [ ] **Step 3: 实现结构化内容生成**

ContentPackage 必须包含：

    video_id
    selling_point
    core_idea
    audience
    scene
    pain_point
    angle
    topic
    publish_title
    cover_title
    people
    closing_speaker_id
    script_segments
    storyboard_prompt
    video_prompt
    final_feeling
    filming_advice

TextProvider 有 native_agent 和 openai_compatible 两种模式。native_agent 通过 ActionBroker 请求结构化 JSON；openai_compatible 使用启动配置中的 base_url、model 和环境变量名。返回值必须通过 ContentPackage.from_dict，不接受自由文本继续流转。

内容生成先根据产品图片和本条唯一卖点分析适用人群、使用场景、核心痛点、卖点切入角度和选题方向；不得判断、推测或编写疾病、伤情、治疗、康复结论。默认每个卖点生成一套 ContentPackage；用户在启动确认单指定多套时，按 Task 3 的数量分配逐条生成独立视频。

validate_content 实现标题、封面标题、人物、唯一卖点、三时间段、15 秒、对话字数、结尾同时包含“买了/用了/换了爱优护电动轮椅后”语义、具体改善益处和柔和购买引导、无编造参数、无字幕、直线和折叠限制。每条只接受一个 publish_title；cover_title 必须从发布标题的核心痛点或利益点压缩得到，目标 4 至 6 个汉字但不强制包含“电动轮椅”。每个人物必须有稳定的 id、身份、性别、年龄感、位置、动作和是否说话；人物列表、脚本说话人、分镜人物和视频提示词人物逐项一致。

tests/fixtures/valid_content.json 保存 Step 1 中 content_package 的完整默认字典，供后续图片、执行和端到端测试读取；测试不得依赖真实业务任务输出。

- [ ] **Step 4: 运行内容测试**

Run: python -m pytest tests/test_content_pipeline.py -v
Expected: 全部通过。

- [ ] **Step 5: 提交**

    git add product_video_skill/providers/text.py product_video_skill/validation product_video_skill/workflow.py tests/fixtures/valid_content.json tests/test_content_pipeline.py
    git commit -m "feat: add structured content generation and validation"

### Task 7: 分镜图动作、参考图选择和三次 QA

**Files:**
- Create: product_video_skill/providers/image.py
- Create: product_video_skill/validation/image.py
- Test: tests/test_image_and_cover_pipeline.py

**Interfaces:**
- Produces: resolve_image_provider(capabilities, config) -> ImageProvider、choose_product_references(images, prompt) -> tuple[Path, ...]、request_storyboard(record, package) -> ActionRequest、validate_storyboard(result) -> ImageQaResult。

- [ ] **Step 1: 写分镜重试失败测试**

    import json
    from pathlib import Path
    from PIL import Image
    from product_video_skill.models import VideoRecord
    from product_video_skill.providers.image import choose_product_references, resolve_image_provider
    from product_video_skill.providers.text import ContentPackage
    from product_video_skill.workflow import generate_storyboard_with_retry

    class FakeImageProvider:
        def __init__(self, qa_scores):
            self.qa_scores = iter(qa_scores)

        def generate(self, output: Path, prompt: str, references: tuple[Path, ...]) -> Path:
            Image.new("RGB", (768, 1365), "white").save(output)
            return output

        def evaluate(self, image: Path):
            score = next(self.qa_scores)
            return {
                "score": score,
                "product_shape_ok": score >= 0.90,
                "logo_ok": score >= 0.90,
                "people_ok": True,
                "scene_ok": True,
                "extra_text_found": False,
                "deformation_notes": "产品外形不稳定",
            }

    def test_native_codex_image_is_default_and_api_is_fallback():
        native = resolve_image_provider(
            capabilities={"native_image_generation": True},
            config={"api_base_url": "https://image.example.invalid", "model": "fallback-image"},
        )
        fallback = resolve_image_provider(
            capabilities={"native_image_generation": False},
            config={"api_base_url": "https://image.example.invalid", "model": "fallback-image"},
        )
        assert native.mode == "native_agent"
        assert fallback.mode == "openai_compatible"

    def test_reference_selector_uses_one_primary_and_at_most_two_auxiliary(tmp_path):
        images = []
        for name in ("正侧45度.png", "控制器细节.png", "侧面.png", "背面.png"):
            path = tmp_path / name
            Image.new("RGB", (768, 1365), "white").save(path)
            images.append(path)
        selected = choose_product_references(tuple(images), "老人坐轮椅正侧45度角")
        assert selected[0].name == "正侧45度.png"
        assert 1 <= len(selected) <= 3

    def test_storyboard_stops_after_three_failed_attempts(tmp_path):
        record = VideoRecord.create("V001", "操作简单", tmp_path / "V001")
        content = ContentPackage.from_dict(json.loads(
            Path("tests/fixtures/valid_content.json").read_text(encoding="utf-8")
        ))
        fake_image_provider = FakeImageProvider([0.61, 0.72, 0.84])
        result = generate_storyboard_with_retry(
            record=record,
            content=content,
            provider=fake_image_provider,
            max_attempts=3,
        )
        assert result.status == "manual_required"
        assert result.attempt_count == 3
        assert len(list((tmp_path / "V001" / "失败版本").glob("分镜图_*.png"))) == 3

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_image_and_cover_pipeline.py::test_storyboard_stops_after_three_failed_attempts -v
Expected: FAIL，提示目标函数不存在。

- [ ] **Step 3: 实现生图和视觉 QA 契约**

ImageProvider 支持 native_agent 和 openai_compatible。检测到 Codex/当前 Agent 原生生图能力时默认使用 native_agent；没有原生能力时，必须使用启动确认单里已确认的 API base_url、模型和密钥环境变量，不能运行到节点 3 才询问。输入必须包含分镜提示词、9:16、主参考图和最多两张辅助图。

ImageQaResult 必须包含：

    score
    product_shape_ok
    logo_ok
    people_ok
    scene_ok
    extra_text_found
    deformation_notes

只有 score >= 0.90 且所有布尔项满足规则时通过。每次失败保存图片、提示词、参考图和失败说明；第三次失败转换到 IMAGE_REVIEW 或 MANUAL_REQUIRED，不阻塞批次。

- [ ] **Step 4: 运行分镜测试**

Run: python -m pytest tests/test_image_and_cover_pipeline.py -v
Expected: 分镜相关测试通过。

- [ ] **Step 5: 提交**

    git add product_video_skill/providers/image.py product_video_skill/validation/image.py tests/test_image_and_cover_pipeline.py
    git commit -m "feat: add storyboard generation and visual qa"

### Task 8: 封面渲染和发布正文落盘

**Files:**
- Create: product_video_skill/media/__init__.py
- Create: product_video_skill/media/cover.py
- Modify: product_video_skill/workflow.py
- Modify: tests/test_image_and_cover_pipeline.py
- Modify: tests/test_content_pipeline.py

**Interfaces:**
- Produces: choose_cover_reference(reference_dir, content) -> Path、render_cover(storyboard, title, reference, output) -> Path、read_cover_metadata(path) -> dict、finalize_publish_body(main_text, profile) -> str、split_body_and_tags(body) -> tuple[str, str]、write_content_files(record, package, body) -> None。

- [ ] **Step 1: 写封面和正文失败测试**

    from pathlib import Path
    from PIL import Image
    from product_video_skill.config import ProductProfile
    from product_video_skill.media.cover import read_cover_metadata, render_cover
    from product_video_skill.workflow import finalize_publish_body, split_body_and_tags

    def test_cover_keeps_storyboard_size_and_writes_exact_title(tmp_path):
        storyboard = tmp_path / "分镜图.png"
        reference = tmp_path / "参考封面.png"
        Image.new("RGB", (768, 1365), "white").save(storyboard)
        Image.new("RGB", (768, 1365), "navy").save(reference)
        output = tmp_path / "封面图.png"
        render_cover(storyboard, "爸妈敢出门", reference, output)
        assert Image.open(output).size == (768, 1365)
        assert read_cover_metadata(output)["title"] == "爸妈敢出门"

    def test_body_length_excludes_fixed_hashtags():
        profile = ProductProfile.load(Path("profiles/爱优护电动轮椅_淘宝天猫光合.json"))
        main_text = (
            "以前带老人下楼，总担心操作复杂，家里人要一直跟在旁边。"
            "用了爱优护电动轮椅后，老人自己很快就能上手，平时在小区出门顺手多了，"
            "家属也不用每一步都帮忙。有同样出门需求的家庭，可以了解一下爱优护电动轮椅。"
        )
        body = finalize_publish_body(main_text, profile)
        main_text, tags = split_body_and_tags(body)
        assert 80 <= sum("\u4e00" <= char <= "\u9fff" for char in main_text) <= 150
        assert tuple(tags.split()) == profile.fixed_hashtags

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_image_and_cover_pipeline.py tests/test_content_pipeline.py -v
Expected: FAIL，提示 render_cover 或 finalize_publish_body 不存在。

- [ ] **Step 3: 实现确定性封面和正文写入**

choose_cover_reference 只扫描技能根目录 `封面图参考/` 第一层的 PNG、JPG、JPEG、WEBP，按场景和构图自动选择一张最匹配参考，不递归读取子文件夹。封面以已通过的分镜图为底图，只学习参考图的标题位置、主色、描边、留白和层级。中文文字由 Pillow 使用可配置字体绘制；不得让生图模型生成汉字。PNG metadata 写入 exact title、reference path 和 render version，方便测试和追溯。

正文生成读取最终脚本与分镜 QA 结果，输出 80 至 150 个汉字，再按固定顺序追加四个话题。写入：

    策划内容.md
    标题.txt
    分镜图.png
    封面图.png
    发布正文.md

- [ ] **Step 4: 运行测试**

Run: python -m pytest tests/test_image_and_cover_pipeline.py tests/test_content_pipeline.py -v
Expected: 全部通过。

- [ ] **Step 5: 提交**

    git add product_video_skill/media product_video_skill/workflow.py tests/test_image_and_cover_pipeline.py tests/test_content_pipeline.py
    git commit -m "feat: add deterministic covers and publishing copy"

---

## 里程碑三：AutoDL.Art 执行链路

### Task 9: 新 MiniMax-H3 API 客户端

**Files:**
- Create: product_video_skill/providers/autodl_h3.py
- Test: tests/test_autodl_h3.py

**Interfaces:**
- Produces: build_h3_prompt(*, people, dialogue, video_prompt="") -> str、AutoDLH3Client(base_url, api_key, session)、submit(request) -> SubmittedTask、query(task_id) -> RemoteTask、download_url(task_id) -> str。

- [ ] **Step 1: 写 API 契约失败测试**

    from pathlib import Path
    from product_video_skill.providers.autodl_h3 import AutoDLH3Client, H3Request, build_h3_prompt

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"task_id": "task-001", "request_id": "request-001"}

    class FakeSession:
        def __init__(self):
            self.calls = []

        def post(self, url, headers, json, timeout):
            self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return FakeResponse()

    def test_submit_uses_new_h3_endpoint_and_first_frame(tmp_path):
        frame = tmp_path / "分镜图.png"
        frame.write_bytes(b"image-bytes")
        session = FakeSession()
        client = AutoDLH3Client(
            base_url="https://www.autodl.art/api/v1/minimax/v2",
            api_key="test-token",
            session=session,
        )
        submitted = client.submit(
            H3Request(
                prompt="固定镜头，自然对白",
                first_frame=frame,
                resolution="768P",
                duration=15,
                ratio="9:16",
            )
        )
        request = session.calls[0]
        assert request["url"].endswith("/api/v1/minimax/v2/video_generation")
        assert request["json"]["aigc_watermark"] is False
        assert request["json"]["content"][1]["role"] == "first_frame"
        assert request["json"]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert submitted.task_id == "task-001"

    def test_h3_prompt_uses_people_list_for_native_voice_and_forbids_bgm():
        prompt = build_h3_prompt(
            people=(
                {"id": "P1", "identity": "老人", "gender": "女", "age_feel": "70岁左右"},
                {"id": "P2", "identity": "家属", "gender": "女", "age_feel": "40岁左右"},
            ),
            dialogue=(
                {"speaker_id": "P2", "text": "这个操作会不会很难？"},
                {"speaker_id": "P1", "text": "用了爱优护电动轮椅后，出门更方便，可以了解一下。"},
            ),
        )
        assert "两位女性" in prompt
        assert "根据人物年龄感自动匹配自然音色" in prompt
        assert "仅保留人物对白和轻微环境声" in prompt
        assert "不要背景音乐" in prompt

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_autodl_h3.py -v
Expected: FAIL，提示 autodl_h3 模块不存在。

- [ ] **Step 3: 实现客户端**

固定端点：

    POST /api/v1/minimax/v2/video_generation
    GET  /api/v1/minimax/v2/query/video_generation/{task_id}

请求使用 Authorization: Bearer 加 api_key。first_frame 本地文件编码为以 data:image/png;base64,、data:image/jpeg;base64, 或 data:image/webp;base64, 开头的 Data URL，禁止写入公共长期 URL。

同一个 MiniMax-H3 视频生成请求直接生成画面、人物对白和自然音轨，不调用第二个 TTS/配音接口。build_h3_prompt 必须严格复用人物清单和脚本说话人，根据身份、性别和年龄感描述自然音色；只允许对白与轻微环境声，明确禁止 BGM。人物数量、性别、对白顺序和台词须与 ContentPackage 完全一致。

解析器同时接受根级 task_id 和 data.task_id；查询状态归一化为 queued、running、succeeded、failed、cancelled。任何响应都不得在异常信息中输出 Authorization。

- [ ] **Step 4: 运行客户端测试**

Run: python -m pytest tests/test_autodl_h3.py -v
Expected: 全部通过。

- [ ] **Step 5: 提交**

    git add product_video_skill/providers/autodl_h3.py tests/test_autodl_h3.py
    git commit -m "feat: add AutoDL MiniMax H3 v2 client"

### Task 10: 预算、请求哈希和并发调度

**Files:**
- Create: product_video_skill/budget.py
- Create: product_video_skill/scheduler.py
- Test: tests/test_scheduler_and_budget.py

**Interfaces:**
- Produces: estimate_cost(resolution, duration, count, retry_count, prices) -> CostEstimate、request_hash(H3Request) -> str、BatchScheduler.run_ready(records)。

- [ ] **Step 1: 写预算与防重复失败测试**

    from decimal import Decimal
    from pathlib import Path
    from product_video_skill.budget import estimate_cost
    from product_video_skill.models import VideoRecord, VideoState
    from product_video_skill.scheduler import BatchScheduler

    class FakeClient:
        def __init__(self):
            self.submit_count = 0

        def submit(self, request):
            self.submit_count += 1
            return {"task_id": "task-001"}

    def test_current_reference_price_and_single_retry_budget():
        estimate = estimate_cost(
            resolution="768P",
            duration=15,
            count=5,
            retry_count=1,
            prices={"768P": Decimal("0.45"), "2K": Decimal("0.72")},
        )
        assert estimate.base == Decimal("33.75")
        assert estimate.maximum == Decimal("67.50")

    def test_scheduler_never_resubmits_known_hash(tmp_path):
        fake_client = FakeClient()
        ready_record = VideoRecord.create("V001", "操作简单", tmp_path / "V001")
        ready_record.state = VideoState.READY_TO_SUBMIT
        ready_record.request_payload = {
            "prompt": "固定镜头",
            "first_frame": str(tmp_path / "分镜图.png"),
            "resolution": "768P",
            "duration": 15,
            "ratio": "9:16",
        }
        (tmp_path / "分镜图.png").write_bytes(b"image-bytes")
        scheduler = BatchScheduler(fake_client, concurrency=3)
        scheduler.run_ready([ready_record, ready_record])
        assert fake_client.submit_count == 1

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_scheduler_and_budget.py -v
Expected: FAIL，提示 budget 或 scheduler 不存在。

- [ ] **Step 3: 实现预算台账和 ThreadPoolExecutor 调度**

使用 Decimal 计算费用，不使用 float。任务提交前预留费用；任务完成后按真实 usage 更新。若下一条提交会超过 max_budget_yuan，则保持未提交任务为 READY_TO_SUBMIT，在其 blocked_reason 写入 `budget_exceeded`，并把批次标记为系统性暂停；用户调整并重新确认预算后才可恢复，绝不自动提交超预算任务。

每个批次启动时把当时查询或由用户提供并确认的 768P/2K 实时单价、会员状态、查询时间和来源写进 `启动确认单.json`；必须在同一张确认单明确询问本批次选 768P 还是 2K，默认建议 768P。设计阶段截图中的 ¥0.45/秒和 ¥0.72/秒仅作为测试夹具，不得在真实批次中当作永久价格。

默认 concurrency=3。请求哈希必须覆盖最终 prompt、首帧文件 SHA-256、分辨率、时长、比例和水印参数。已有 task_id 或同批次相同哈希时禁止提交。

超时且无法判断是否提交成功时标记 SUBMIT_UNKNOWN，不自动重提。

- [ ] **Step 4: 运行预算调度测试**

Run: python -m pytest tests/test_scheduler_and_budget.py -v
Expected: 全部通过。

- [ ] **Step 5: 提交**

    git add product_video_skill/budget.py product_video_skill/scheduler.py tests/test_scheduler_and_budget.py
    git commit -m "feat: add budgeted idempotent batch scheduler"

### Task 11: 轮询、下载和媒体技术校验

**Files:**
- Create: product_video_skill/media/download.py
- Create: product_video_skill/media/probe.py
- Create: product_video_skill/poller.py
- Test: tests/test_poll_and_download.py

**Interfaces:**
- Produces: Poller.wait(task_id, timeout_seconds=3600) -> RemoteTask、download_atomic(url, output, retries=4, session=None) -> Path、probe_video(path) -> VideoProbe。

- [ ] **Step 1: 写轮询和下载失败测试**

    from product_video_skill.poller import Poller

    class PollClient:
        def __init__(self):
            self.statuses = iter(["queued", "running"])

        def query(self, task_id):
            return {"task_id": task_id, "status": next(self.statuses)}

    def test_poll_timeout_preserves_task_id():
        fake_client = PollClient()
        result = Poller(fake_client, interval_seconds=0).wait("task-001", timeout_seconds=0)
        assert result.local_status == "poll_timeout"
        assert result.task_id == "task-001"

    import shutil
    import subprocess
    import pytest
    from product_video_skill.media.download import download_atomic
    from product_video_skill.media.probe import probe_video

    class DownloadResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield self.payload

    class DownloadSession:
        def __init__(self, payload):
            self.payload = payload

        def get(self, url, timeout, stream):
            return DownloadResponse(self.payload)

    def make_valid_mp4(path):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            pytest.skip("ffmpeg and ffprobe are required")
        subprocess.run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=black:s=320x568:r=24:d=15",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=15",
            "-shortest", "-t", "15",
            "-c:v", "libx264", "-c:a", "aac", str(path),
        ], check=True)

    def test_download_uses_part_file_and_validates_media(tmp_path):
        source = tmp_path / "source.mp4"
        make_valid_mp4(source)
        output = tmp_path / "视频.mp4"
        session = DownloadSession(source.read_bytes())
        download_atomic("https://example.invalid/video.mp4", output, retries=4, session=session)
        assert output.exists()
        assert not output.with_suffix(".mp4.part").exists()
        assert probe_video(output).has_audio is True
        assert probe_video(output).has_non_silent_audio is True

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_poll_and_download.py -v
Expected: FAIL，提示 poller、download 或 probe 不存在。

- [ ] **Step 3: 实现轮询和下载**

Poller 默认 20 秒，网络错误递增重试 5 次，单条 3600 秒后返回 poll_timeout 而不是 failed。限流时优先使用 Retry-After。

download_atomic 立即下载成功任务，先写 视频.mp4.part，完成后调用 ffprobe JSON：

    ffprobe -v error -show_streams -show_format -of json 视频.mp4.part

验证可解码、约 15 秒、9:16、预期分辨率、有效且非静音的音轨和非零文件大小后再 replace。非静音检查使用 ffmpeg `volumedetect`，全程静音视为下载/生成技术校验不通过。失败最多 4 次。

- [ ] **Step 4: 运行媒体测试**

Run: python -m pytest tests/test_poll_and_download.py -v
Expected: 全部通过；若 ffprobe 不可用，测试明确 SKIP 并输出安装要求。

- [ ] **Step 5: 提交**

    git add product_video_skill/media/download.py product_video_skill/media/probe.py product_video_skill/poller.py tests/test_poll_and_download.py
    git commit -m "feat: add resumable polling and verified downloads"

### Task 12: 集成节点 5 至 9

**Files:**
- Modify: product_video_skill/workflow.py
- Modify: product_video_skill/cli.py
- Create: tests/test_execution_pipeline.py

**Interfaces:**
- Produces: WorkflowEngine(batch_dir, store, submitter, poller, downloader)、submit_ready()、poll_active()、download_succeeded()、run_execution_cycle()。
- Consumes: BatchScheduler、AutoDLH3Client、Poller、download_atomic、BatchStore。

- [ ] **Step 1: 写执行链路失败测试**

    from pathlib import Path
    from product_video_skill.models import VideoRecord, VideoState
    from product_video_skill.storage import BatchStore
    from product_video_skill.workflow import WorkflowEngine

    class Submitter:
        def submit(self, record):
            return {"task_id": "task-001", "request_id": "request-001"}

    class SuccessfulPoller:
        def wait(self, task_id, timeout_seconds=3600):
            return {
                "task_id": task_id,
                "status": "succeeded",
                "url": "https://example.invalid/video.mp4",
            }

    def downloader(url, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"verified-mp4")
        return output

    def test_execution_cycle_submits_polls_and_downloads(tmp_path):
        store = BatchStore(tmp_path)
        record = VideoRecord.create("V001", "操作简单", tmp_path / "V001")
        record.state = VideoState.READY_TO_SUBMIT
        store.save_video(record)
        engine = WorkflowEngine(
            batch_dir=tmp_path,
            store=store,
            submitter=Submitter(),
            poller=SuccessfulPoller(),
            downloader=downloader,
        )
        engine.run_execution_cycle()
        record = store.load_video("V001")
        assert record.task_id == "task-001"
        assert record.state is VideoState.AWAITING_REVIEW
        assert (record.project_dir / "视频.mp4").exists()

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_execution_pipeline.py -v
Expected: FAIL，提示 run_execution_cycle 不存在。

- [ ] **Step 3: 实现状态驱动执行**

每个阶段先保存请求快照，再调用远端，再保存 task_id，然后轮询和下载。状态必须按 READY_TO_SUBMIT → SUBMITTING → SUBMITTED → POLLING → DOWNLOADED → AWAITING_REVIEW 运行。

提交成功后立即把 task_id、request_id、request_hash、状态、预计费用和时间戳原子写入单条 `任务信息.json`，并同步更新批次根目录 `批次任务表.json`。进程在任意阶段重启时，必须优先加载这两份记录并恢复轮询，已有 task_id 或已知 request_hash 不得再次付费提交。

批量结束统一生成 批次汇总.md，列出成功 task_id、失败、超时、提交状态待确认、费用和待人工项目。

内容、分镜、单条提交、单条轮询、单条下载和单条验收异常必须捕获到对应 VideoRecord，标记失败原因后继续调度其他项目。只有 AutoDL/文本/生图 API 整体鉴权失效、余额不足、预算超限或必要配置失效时，才把批次写为 `paused_system` 并停止新的远端调用；已取得 task_id 的任务信息仍保留，可在恢复后继续查询。所有单条失败和系统暂停原因仅在批次结束或暂停汇总时统一报告。

- [ ] **Step 4: 运行里程碑三测试**

Run: python -m pytest tests/test_autodl_h3.py tests/test_scheduler_and_budget.py tests/test_poll_and_download.py tests/test_execution_pipeline.py -v
Expected: 全部通过。

- [ ] **Step 5: 提交**

    git add product_video_skill/workflow.py product_video_skill/cli.py tests/test_execution_pipeline.py
    git commit -m "feat: integrate AutoDL execution workflow"

---

## 里程碑四：批量验收、学习和跨 Agent 封装

### Task 13: 分配本地验收端口并更新项目登记

**Files:**
- Create: scripts/allocate_review_port.py
- Modify: C:\Users\Administrator\.codex\PORT_REGISTRY.json
- Modify: PROJECT_INFO.md
- Test: tests/test_port_registry.py

**Interfaces:**
- Produces: allocate_backend_port(registry_path, project_path, port_available) -> int。

- [ ] **Step 1: 写端口分配失败测试**

    import json
    from pathlib import Path
    from scripts.allocate_review_port import allocate_backend_port

    def test_reuses_existing_project_port_and_chooses_smallest_free(tmp_path):
        registry = {
            "projectRoot": r"D:\0-AI 项目",
            "projects": [
                {"projectPath": r"D:\0-AI 项目\甲", "backendPort": 3001},
                {"projectPath": r"D:\0-AI 项目\乙", "backendPort": 3002},
            ],
        }
        path = tmp_path / "PORT_REGISTRY.json"
        path.write_text(json.dumps(registry), encoding="utf-8")
        available = lambda port: port not in {3001, 3002}
        assert allocate_backend_port(path, Path(r"D:\0-AI 项目\ayh-h3"), available) == 3003
        assert allocate_backend_port(path, Path(r"D:\0-AI 项目\ayh-h3"), available) == 3003

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_port_registry.py -v
Expected: FAIL，提示 allocate_review_port 不存在。

- [ ] **Step 3: 实现并执行安全端口登记**

脚本读取 C:\Users\Administrator\.codex\PORT_REGISTRY.json；如果 ayh-h3 已登记则复用，否则从 3001 至 3199 选择未登记且 socket 未占用的最小端口。写入前保留其他项目原始数据，使用 UTF-8 原子替换。

Run: python scripts/allocate_review_port.py
Expected: 输出唯一整数端口，并在注册表新增 projectName=爱优护 H3 视频生成技能、projectPath=D:\0-AI 项目\ayh-h3、techId=ayh-h3；backendPort 字段必须等于脚本输出的整数。

PROJECT_INFO.md 将“后端端口”和“本地访问地址”更新为注册值；不声明前端端口，因为页面由同一 Python 服务提供。

- [ ] **Step 4: 运行端口测试**

Run: python -m pytest tests/test_port_registry.py -v
Expected: 全部通过。

- [ ] **Step 5: 提交仓库内文件**

    git add scripts/allocate_review_port.py PROJECT_INFO.md tests/test_port_registry.py
    git commit -m "chore: register local review service port"

说明：PORT_REGISTRY.json 位于仓库外，不加入 Git，但必须在实施交付中报告已登记。

### Task 14: 批量验收页面和结果回写

**Files:**
- Create: product_video_skill/review/__init__.py
- Create: product_video_skill/review/auto_qa.py
- Create: product_video_skill/review/server.py
- Create: product_video_skill/review/results.py
- Create: product_video_skill/review/templates/batch_review.html
- Test: tests/test_review_server.py

**Interfaces:**
- Produces: extract_review_contact_sheet(video, output, runner) -> Path、request_auto_qa(item_dir, content, active_rules, broker) -> tuple[ActionRequest, ActionRequest]、finalize_auto_qa(item_dir, video_analysis, transcript) -> AutoQaReport、build_review_manifest(batch_dir) -> dict、ReviewServer.serve()、parse_review_submission(payload) -> BatchReviewResult、submit_review(batch_dir, payload) -> BatchReviewResult。

- [ ] **Step 1: 写验收结果失败测试**

    import pytest
    from PIL import Image
    from product_video_skill.actions import ActionBroker
    from product_video_skill.review.auto_qa import finalize_auto_qa, request_auto_qa
    from product_video_skill.review.server import build_review_manifest
    from product_video_skill.review.results import (
        ReviewValidationError,
        parse_review_submission,
        submit_review,
    )

    def test_failed_video_requires_reason():
        payload = {
            "items": [
                {"video_id": "V001", "decision": "passed", "reason": ""},
                {"video_id": "V002", "decision": "failed", "reason": ""},
            ]
        }
        with pytest.raises(ReviewValidationError):
            parse_review_submission(payload)

    def test_submission_writes_batch_and_item_results(tmp_path):
        batch = tmp_path / "20260826_批次001"
        item = batch / "V001_轻便_爸妈敢出门"
        item.mkdir(parents=True)
        payload = {
            "items": [
                {"video_id": "V001", "decision": "passed", "reason": "", "suggestion": ""}
            ]
        }
        result = submit_review(batch, payload)
        assert (batch / "批次验收结果.json").exists()
        assert (item / "人工验收结果.md").exists()
        assert result.items[0].decision == "passed"

    def test_auto_qa_writes_required_materials_and_enters_manifest(tmp_path):
        batch = tmp_path / "20260826_批次001"
        item = batch / "V001_轻便_爸妈敢出门"
        item.mkdir(parents=True)
        (item / "策划内容.md").write_text("人物：老人、家属", encoding="utf-8")
        Image.new("RGB", (768, 1365), "white").save(item / "验收预览图.jpg")
        broker = ActionBroker(batch / "actions")
        actions = request_auto_qa(
            item_dir=item,
            content={"people": ["老人", "家属"], "selling_point": "轻便"},
            active_rules=("轮椅只能直线行驶",),
            broker=broker,
        )
        assert {action.kind for action in actions} == {"video_analysis", "speech_transcription"}
        report = finalize_auto_qa(
            item_dir=item,
            video_analysis={
                "product_logo_ok": True,
                "people_consistent": True,
                "single_shot": True,
                "motion_rules_ok": True,
                "subtitle_absent": True,
                "speaker_and_lip_sync_ok": True,
                "benefit_and_cta_ok": True,
                "bgm_absent": True,
                "historical_rules_ok": True,
                "notes": [],
            },
            transcript="用了爱优护电动轮椅后，出门方便多了，可以了解一下。",
        )
        assert report.passed is True
        assert (item / "语音转写.txt").exists()
        assert (item / "自动验收报告.md").exists()
        assert build_review_manifest(batch)["items"][0]["auto_qa"]["passed"] is True

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_review_server.py -v
Expected: FAIL，提示 review 模块不存在。

- [ ] **Step 3: 实现本地验收页面**

auto_qa.py 先用 ffmpeg 从 15 秒视频等距抽取 9 帧并生成 `验收预览图.jpg`。随后通过 ActionBroker 一次性创建 `video_analysis` 和 `speech_transcription`：分析载荷包含成片、预览图、人物清单、唯一卖点、脚本、当前正式规则；转写载荷包含成片和人物对白。`video_analysis` 的结构化结果必须逐项给出产品与 Logo、人物数量/身份/性别、单镜头、动作限制、无字幕、说话人与嘴型、改善益处加购买引导、无 BGM、历史错误规则是否通过及证据时间点。finalize_auto_qa 必须写 `语音转写.txt` 和 `自动验收报告.md`；自动不通过只进入报告，绝不能代替用户最终验收。

页面在一个批次内显示全部视频卡片：视频播放、封面、发布标题、封面标题、卖点、自动验收、task_id、费用、通过/不通过、失败原因和修改建议。批次根目录保存可离线打开的 `批次验收报告.html`；启动本地服务时复用 Task 13 登记端口。

JavaScript 在提交前检查所有视频均已选择，所有 failed 项原因非空。POST /api/review 写入 批次验收结果.json、批次验收结果.md 和每条 人工验收结果.md。静态文件路径必须限制在当前批次目录，防止目录穿越。

- [ ] **Step 4: 运行验收页面测试**

Run: python -m pytest tests/test_review_server.py -v
Expected: 全部通过。

- [ ] **Step 5: 提交**

    git add product_video_skill/review tests/test_review_server.py
    git commit -m "feat: add interactive batch review report"

### Task 15: 候选经验、正式规则和一次重跑

**Files:**
- Create: product_video_skill/learning/__init__.py
- Create: product_video_skill/learning/repository.py
- Create: product_video_skill/learning/retrospective.py
- Create: product_video_skill/versioning.py
- Modify: product_video_skill/workflow.py
- Test: tests/test_learning.py

**Interfaces:**
- Produces: ExperienceRepository.add_candidate()、RetrospectiveEngine.analyze()、promote(candidate_id, approved_by)、VersionManager.create_initial() -> Path、VersionManager.create_rerun() -> Path、VersionManager.promote(version_dir) -> Path。

- [ ] **Step 1: 写经验生命周期失败测试**

    import pytest
    from product_video_skill.learning.repository import ExperienceRepository
    from product_video_skill.versioning import RetryLimitReached, VersionManager

    def test_failed_review_creates_candidate_but_not_active_rule(tmp_path):
        repository = ExperienceRepository(tmp_path)
        candidate = repository.add_candidate(
            product="爱优护轻便侠218",
            category="电动轮椅",
            model="MiniMax-H3",
            workflow="image_to_video",
            issue="轮椅发生转弯",
            issue_type="motion",
            severity="high",
            evidence_paths=("V001/视频版本/V01_初次生成/视频.mp4",),
            proposed_rule="行驶画面只允许直线缓慢前进",
        )
        assert candidate.status == "candidate"
        assert repository.active_rules(product="爱优护轻便侠218") == []

    def test_only_verified_and_user_approved_candidate_is_promoted(tmp_path):
        repository = ExperienceRepository(tmp_path)
        candidate = repository.add_candidate(
            product="爱优护轻便侠218",
            category="电动轮椅",
            model="MiniMax-H3",
            workflow="image_to_video",
            issue="轮椅发生转弯",
            issue_type="motion",
            severity="high",
            evidence_paths=("V001/视频版本/V01_初次生成/视频.mp4",),
            proposed_rule="行驶画面只允许直线缓慢前进",
        )
        repository.mark_verified(candidate.candidate_id, rerun_passed=True)
        repository.promote(candidate.candidate_id, approved_by="user")
        assert repository.active_rules(product=candidate.product)[0].status == "active"

    def test_only_v01_and_v02_exist_and_passed_version_is_promoted(tmp_path):
        item = tmp_path / "V001_操作简单_爸妈会操作"
        manager = VersionManager(item)
        v01 = manager.create_initial()
        assert v01.name == "V01_初次生成"
        v02 = manager.create_rerun()
        (v02 / "视频.mp4").write_bytes(b"verified-second-version")
        promoted = manager.promote(v02)
        assert promoted == item / "视频.mp4"
        assert promoted.read_bytes() == b"verified-second-version"
        with pytest.raises(RetryLimitReached):
            manager.create_rerun()

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_learning.py -v
Expected: FAIL，提示 learning 模块不存在。

- [ ] **Step 3: 实现分层经验库和重跑分流**

经验记录必须有 scope、product、category、model、workflow、issue_type、severity、evidence_paths、proposed_rule、verification_result、status、created_at、updated_at。

人工失败原因按脚本、分镜、正文、视频提示词、API/下载、模型边界分流。学习模式输出批次复盘报告供用户确认；自动模式只能读取正式规则，不能自动把新候选升级。

VersionManager 创建固定目录 `视频版本/V01_初次生成/` 和 `视频版本/V02_唯一一次重跑/`，每个版本独立保存提交请求、task_id、费用、视频和验收证据；第三次创建必须抛出 RetryLimitReached。最终通过版本以原子复制方式写到项目根目录 `视频.mp4`。V02 仍失败时进入 MANUAL_REQUIRED，不再提交任何付费任务。

- [ ] **Step 4: 运行学习测试**

Run: python -m pytest tests/test_learning.py -v
Expected: 全部通过。

- [ ] **Step 5: 提交**

    git add product_video_skill/learning product_video_skill/versioning.py product_video_skill/workflow.py tests/test_learning.py
    git commit -m "feat: add validated retrospective learning"

### Task 16: 跨 Agent 适配、技能文档和端到端测试

**Files:**
- Modify: SKILL.md
- Modify: AGENTS.md if repository-local file is introduced
- Modify: README.md
- Modify: scripts/.env.example
- Create: adapters/codex/README.md
- Create: adapters/workbuddy/README.md
- Create: adapters/hermes/README.md
- Create: adapters/generic/README.md
- Create: data/产品卖点库/.gitkeep
- Create: data/候选经验/.gitkeep
- Create: data/正式经验/.gitkeep
- Create: data/模型能力边界/.gitkeep
- Create: 封面图参考/.gitkeep
- Create: tests/test_end_to_end.py

**Interfaces:**
- Consumes: CLI、ActionBroker、WorkflowEngine、ReviewServer、ExperienceRepository。
- Produces: initialize_batch(config) -> BatchContext，以及各 Agent 可执行的相同启动、动作完成、恢复和验收流程。

- [ ] **Step 1: 写无付费端到端失败测试**

    import json
    from decimal import Decimal
    from pathlib import Path
    from PIL import Image
    from product_video_skill.models import BatchConfig, RunMode, VideoState
    from product_video_skill.workflow import WorkflowEngine, initialize_batch

    def make_product_folder(root: Path) -> Path:
        product = root / "爱优护轻便侠218"
        product.mkdir()
        Image.new("RGB", (768, 1365), "white").save(product / "正侧45度.png")
        return product

    def test_mock_batch_completes_all_eleven_nodes(mock_provider_bundle, tmp_path):
        product = make_product_folder(tmp_path)
        config = BatchConfig(
            product_dir=product,
            product_name="爱优护轻便侠218",
            run_mode=RunMode.LEARNING,
            total_videos=1,
            selling_points=("操作简单",),
            resolution="768P",
            duration=15,
            ratio="9:16",
            concurrency=3,
            max_budget_yuan=Decimal("20"),
        )
        batch = initialize_batch(
            config=config,
            profile_path=Path("profiles/爱优护电动轮椅_淘宝天猫光合.json"),
            provider_bundle=mock_provider_bundle,
        )
        engine = WorkflowEngine(batch)
        engine.run_until_blocked()
        mock_provider_bundle.complete_pending_actions(batch.action_broker)
        engine.resume()
        engine.approve_content(["V001"])
        mock_provider_bundle.complete_pending_actions(batch.action_broker)
        engine.resume()
        engine.approve_images(["V001"])
        engine.run_execution_cycle()
        engine.submit_review({
            "items": [
                {"video_id": "V001", "decision": "passed", "reason": "", "suggestion": ""}
            ]
        })
        record = batch.store.load_video("V001")
        assert record.state is VideoState.PASSED
        assert (record.project_dir / "视频.mp4").exists()
        assert (record.project_dir / "发布正文.md").exists()

mock_provider_bundle fixture 在同一测试文件中实现：文本动作返回 tests/fixtures/valid_content.json；生图动作生成 768×1365 PNG 并返回 0.95 QA 分；AutoDL 提交返回 task-001，查询返回 succeeded，下载返回由 ffmpeg 生成的 15 秒 9:16 带音轨 MP4。

- [ ] **Step 2: 运行测试并确认失败**

Run: python -m pytest tests/test_end_to_end.py -v
Expected: FAIL，直到适配入口和完整流程接通。

- [ ] **Step 3: 编写平台适配和文档**

每个 adapter 文档必须给出同一四步：

    1. 读取 SKILL.md 和启动确认单。
    2. 运行 product-video-skill init/resume。
    3. 处理 next-actions 返回的 text_generation、image_generation、visual_qa。
    4. 用 complete-action 回写结果并继续。

SKILL.md 改为通用入口，爱优护规则引用 profile 和 rules 文件。README 更新新架构、15 秒 MiniMax-H3 V2 接口、目录、启动命令、恢复命令、验收命令和安全配置。scripts/.env.example 至少列出 AUTODL_API_KEY、TEXT_API_KEY、IMAGE_API_KEY，但不含真实值。

- [ ] **Step 4: 运行全部无付费验证**

Run: python -m pytest tests -q
Expected: 全部通过。

Run: python -m pytest scripts/test_generate_standard_v2.py scripts/test_generate_d01_first5.py -q
Expected: 旧版兼容测试通过。

Run: python -m product_video_skill.cli --help
Expected: CLI 命令完整。

Run: git grep -n -E "AUTODL_API_KEY=.+|TEXT_API_KEY=.+|IMAGE_API_KEY=.+" -- . ":!scripts/.env.example"
Expected: 无输出。

- [ ] **Step 5: 提交**

    git add SKILL.md README.md scripts/.env.example adapters data 封面图参考 tests/test_end_to_end.py
    git commit -m "feat: package cross-agent product video skill"

### Task 17: 用户批准后的真实付费冒烟测试

**Files:**
- Create at runtime: 用户指定产品目录\生成视频\
- Create at runtime: outputs/live-smoke/启动确认单.json
- Modify after result: docs/verification/2026-08-26-live-smoke-test.md

**Interfaces:**
- Consumes: 完整技能包和用户提供的真实 API 凭据。
- Produces: 一条 15 秒 768P 成片、task_id、费用、验收与复盘证据。

- [ ] **Step 1: 生成付费测试启动确认单**

确认单固定使用：

    产品：用户指定的一个产品目录
    卖点：用户指定的一个卖点
    数量：1
    模式：学习确认
    时长：15 秒
    比例：9:16
    分辨率：768P
    视频基础预计费用：按 AutoDL 当前实时价格计算
    视频重跑次数：0，除非用户再次明确批准预算

- [ ] **Step 2: 等待用户明确批准实时费用**

不得把设计阶段的 ¥6.75 历史参考价当作自动授权。只有用户明确回复批准本次实时费用后才能提交。

- [ ] **Step 3: 运行真实链路**

Run: product-video-skill init --config outputs/live-smoke/启动确认单.json
Expected: 节点 2 和节点 3 在学习模式等待审核；审核后提交一个 MiniMax-H3 任务，取得 task_id，轮询、下载并生成批量验收页。

- [ ] **Step 4: 记录证据并运行回归**

docs/verification/2026-08-26-live-smoke-test.md 必须记录 task_id、分辨率、时长、实际费用、下载文件哈希、人工验收结果和是否形成候选经验，不记录 API 密钥。

Run: python -m pytest tests -q
Expected: 全部通过。

- [ ] **Step 5: 提交验证记录**

    git add docs/verification/2026-08-26-live-smoke-test.md
    git commit -m "test: verify live MiniMax H3 workflow"

---

## 实施顺序与审查门

1. 完成 Tasks 1-4 后审查：状态恢复、启动确认和跨 Agent 动作协议。
2. 完成 Tasks 5-8 后审查：节点 2-4 内容、分镜和封面质量。
3. 完成 Tasks 9-12 后审查：AutoDL V2、预算、防重复、轮询和下载。
4. 完成 Tasks 13-16 后审查：验收页、经验学习、端口登记和技能封装。
5. Task 17 必须等待用户单独批准实时付费预算。

## 最终无付费验收命令

    python -m pytest tests -q
    python -m pytest scripts/test_generate_standard_v2.py scripts/test_generate_d01_first5.py -q
    python -m product_video_skill.cli --help
    git diff --check
    git status --short

预期：新测试全部通过，旧兼容测试通过，CLI 可用，无 whitespace 错误；git status 只显示用户原有未跟踪文件或已明确的实施改动。
