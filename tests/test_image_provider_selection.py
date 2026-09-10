import importlib.util
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill-package" / "product-video-pipeline" / "scripts"


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"test_{name}", SCRIPTS / name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("value", [None, "", "automatic", "gpt_api"])
def test_image_provider_is_required_and_closed_to_unknown_values(value):
    policy = load_script("pipeline_policy.py")
    with pytest.raises(ValueError, match="图片渠道"):
        policy.normalize_image_provider(value)


@pytest.mark.parametrize("provider", ["codex", "chatgpt_web", "third_party_api"])
def test_policy_accepts_exactly_three_image_providers(provider):
    policy = load_script("pipeline_policy.py")
    assert policy.normalize_image_provider(provider) == provider


def test_policy_keeps_legacy_gpt_web_batches_loadable():
    policy = load_script("pipeline_policy.py")
    assert policy.normalize_image_provider("gpt_web") == "gpt_web"


def test_third_party_config_requires_non_secret_fields():
    policy = load_script("pipeline_policy.py")
    valid = {
        "api_name": "Example Images",
        "base_url": "https://images.example.test/v1",
        "model": "image-v1",
        "api_key_env": "EXAMPLE_IMAGE_API_KEY",
        "unit_price_yuan": "0.20",
    }
    assert policy.normalize_image_api_config(valid) == valid
    for key in valid:
        broken = dict(valid)
        broken.pop(key)
        with pytest.raises(ValueError, match=key):
            policy.normalize_image_api_config(broken)
    with pytest.raises(ValueError, match="密钥|secret|明文"):
        policy.normalize_image_api_config({**valid, "api_key": "do-not-store"})
    with pytest.raises(ValueError, match="api_key_env"):
        policy.normalize_image_api_config({**valid, "api_key_env": "sk-live-do-not-store"})
    with pytest.raises(ValueError, match="base_url"):
        policy.normalize_image_api_config({
            **valid,
            "base_url": "https://do-not-store@example.test/v1?api_key=do-not-store",
        })
    assert policy.normalize_image_api_config({
        **valid, "batch_budget_yuan": "5.00"
    }) == valid


@pytest.fixture
def initialization_kwargs(tmp_path):
    product_dir = tmp_path / "product"
    cover_reference_dir = tmp_path / "covers"
    product_dir.mkdir()
    cover_reference_dir.mkdir()
    (product_dir / "product.png").write_bytes(b"product-image")
    (cover_reference_dir / "cover.png").write_bytes(b"cover-reference")
    return {
        "product_dir": product_dir,
        "product_name": "测试产品",
        "selling_points": ["轻便"],
        "total_videos": 1,
        "run_mode": "auto",
        "resolution": "768P",
        "max_budget_yuan": "10.00",
        "cover_reference_dir": cover_reference_dir,
        "knowledge_dir": tmp_path / "knowledge",
        "now": datetime(2026, 9, 9, tzinfo=timezone.utc),
    }


def test_initialize_batch_requires_provider_and_persists_safe_configuration(initialization_kwargs):
    workflow = load_script("workflow_cli.py")
    with pytest.raises(TypeError):
        workflow.initialize_batch(**initialization_kwargs)

    gpt_context = workflow.initialize_batch(
        **initialization_kwargs,
        image_provider="gpt_web",
    )
    gpt_confirmation = json.loads((gpt_context.batch_dir / "启动确认单.json").read_text(encoding="utf-8"))
    assert gpt_confirmation["image_provider"] == "gpt_web"
    assert gpt_confirmation["image_api_config"] == {}
    assert gpt_confirmation["startup_authorization"] == "initial_user_reply"
    assert "首次回复授权 V01" in (gpt_context.batch_dir / "批次汇总.md").read_text(encoding="utf-8")

    config = {
        "api_name": "Example Images",
        "base_url": "https://images.example.test/v1",
        "model": "image-v1",
        "api_key_env": "EXAMPLE_IMAGE_API_KEY",
        "unit_price_yuan": "0.20",
    }
    api_context = workflow.initialize_batch(
        **{**initialization_kwargs, "now": datetime(2026, 9, 10, tzinfo=timezone.utc)},
        image_provider="third_party_api",
        image_api_config=config,
    )
    api_confirmation = json.loads((api_context.batch_dir / "启动确认单.json").read_text(encoding="utf-8"))
    assert api_confirmation["image_provider"] == "third_party_api"
    assert api_confirmation["image_api_config"] == config
    assert "batch_budget_yuan" not in api_confirmation["image_api_config"]


def test_init_cli_requires_explicit_image_provider(initialization_kwargs):
    workflow = load_script("workflow_cli.py")
    base_args = [
        "init",
        "--product-dir", str(initialization_kwargs["product_dir"]),
        "--product-name", initialization_kwargs["product_name"],
        "--selling-point", "轻便",
        "--total", "1",
        "--mode", "auto",
        "--max-budget", "10.00",
        "--cover-reference-dir", str(initialization_kwargs["cover_reference_dir"]),
        "--knowledge-dir", str(initialization_kwargs["knowledge_dir"]),
    ]
    assert workflow.main([
        *base_args,
        "--image-provider", "gpt_web",
    ]) == 0
    config = {
        "api_name": "Example Images",
        "base_url": "https://images.example.test/v1",
        "model": "image-v1",
        "api_key_env": "EXAMPLE_IMAGE_API_KEY",
        "unit_price_yuan": "0.20",
    }
    config_path = initialization_kwargs["knowledge_dir"].parent / "image-api-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    assert workflow.main([
        *base_args,
        "--image-provider", "third_party_api",
        "--image-api-config", str(config_path),
    ]) == 0


@pytest.fixture
def api_config_path(tmp_path):
    config = {
        "api_name": "Example Images",
        "base_url": "https://images.example.test/v1",
        "model": "image-v1",
        "api_key_env": "EXAMPLE_IMAGE_API_KEY",
        "unit_price_yuan": "0.20",
    }
    path = tmp_path / "image-api-config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


@pytest.fixture
def setup_batch(tmp_path):
    runner = load_script("pipeline_runner.py")
    policy = load_script("pipeline_policy.py").load_policy(ROOT / "skill-package" / "product-video-pipeline")
    batch = tmp_path / "batch"
    item = batch / "V001_轻便_待生成"
    task = item / "_工作文件" / "任务状态" / "任务信息.json"
    task.parent.mkdir(parents=True)
    task.write_text(json.dumps({"video_id": "V001", "retry_count": 0, "status": "CREATED"}), encoding="utf-8")
    process = item / "_工作文件" / "生成过程"
    process.mkdir(parents=True)
    (process / "策划内容.json").write_text("{}", encoding="utf-8")
    for prompt in ("分镜提示词.txt", "合理尾帧提示词.txt", "封面提示词.txt"):
        (process / prompt).write_text("vertical wheelchair product image", encoding="utf-8")
    product = tmp_path / "product.png"
    Image.new("RGB", (90, 160), "red").save(product)
    confirmation = {
        "product_images": [str(product)], "cover_reference_dir": str(tmp_path),
        "product_name": "爱优护电动轮椅", "total_videos": 1,
        "resolution": "768P", "duration_seconds": 15, "max_budget_yuan": "10.00",
        "unit_price_yuan": "3.00", "live_price": {"queried_at": "2026-09-08"},
        "image_provider": "gpt_web", "image_api_config": {},
    }
    (batch / "启动确认单.json").write_text(json.dumps(confirmation, ensure_ascii=False), encoding="utf-8")
    return runner, policy, batch, item


def approve_and_select_image(setup_batch, capsys, provider, api_config_path=None):
    runner, _, batch, _ = setup_batch
    confirmation_path = batch / "启动确认单.json"
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    confirmation["image_provider"] = provider
    confirmation["image_api_config"] = (
        json.loads(api_config_path.read_text(encoding="utf-8"))
        if api_config_path is not None else {}
    )
    confirmation_path.write_text(json.dumps(confirmation, ensure_ascii=False), encoding="utf-8")
    args = [
        "approve-start", "--batch", str(batch), "--approved-budget", "10",
        "--estimated-v01-total", "3", "--image-provider", provider,
    ]
    if api_config_path is not None:
        args.extend(["--image-api-config", str(api_config_path)])
    assert runner.main(args) == 0
    return json.loads(capsys.readouterr().out)


def test_approve_start_refuses_missing_image_provider(setup_batch, capsys):
    runner, _, batch, _ = setup_batch
    with pytest.raises(SystemExit):
        runner.main([
            "approve-start", "--batch", str(batch),
            "--approved-budget", "10", "--estimated-v01-total", "3",
        ])
    assert "image-provider" in capsys.readouterr().err


def test_third_party_approval_requires_the_named_api_credential(
    setup_batch, capsys, api_config_path, monkeypatch
):
    monkeypatch.delenv("EXAMPLE_IMAGE_API_KEY", raising=False)
    runner, _, batch, _ = setup_batch
    confirmation_path = batch / "启动确认单.json"
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    confirmation["image_provider"] = "third_party_api"
    confirmation["image_api_config"] = json.loads(api_config_path.read_text(encoding="utf-8"))
    confirmation_path.write_text(json.dumps(confirmation, ensure_ascii=False), encoding="utf-8")

    assert runner.main([
        "approve-start", "--batch", str(batch), "--approved-budget", "10",
        "--estimated-v01-total", "3", "--image-provider", "third_party_api",
        "--image-api-config", str(api_config_path),
    ]) == 2
    assert "EXAMPLE_IMAGE_API_KEY" in json.loads(capsys.readouterr().out)["reason"]


@pytest.mark.parametrize(
    ("provider", "kind"),
    [("gpt_web", "GPT_WEB_IMAGE_REQUIRED"),
     ("third_party_api", "THIRD_PARTY_IMAGE_REQUIRED")],
)
def test_approved_provider_selects_exact_image_action(
    setup_batch, capsys, provider, kind, api_config_path, monkeypatch
):
    monkeypatch.setenv("EXAMPLE_IMAGE_API_KEY", "provider-selection-test-secret")
    action = approve_and_select_image(
        setup_batch, capsys, provider,
        api_config_path if provider == "third_party_api" else None,
    )
    assert action["kind"] == kind
    assert action["provider"] == provider
    assert action["action_id"]
    assert {"video_id", "artifact", "prompt_path", "output_path", "reference_paths", "attempt"} <= set(action)
    if provider == "third_party_api":
        assert action["api_config"]["api_key_env"] == "EXAMPLE_IMAGE_API_KEY"
    else:
        assert "api_config" not in action


@pytest.mark.parametrize(
    ("provider", "kind"),
    [("gpt_web", "GPT_WEB_IMAGE_REQUIRED"),
     ("third_party_api", "THIRD_PARTY_IMAGE_REQUIRED")],
)
def test_native_4k_image_action_uses_compiled_prompt_and_exact_dimensions(
    setup_batch, capsys, provider, kind, api_config_path, monkeypatch
):
    monkeypatch.setenv("EXAMPLE_IMAGE_API_KEY", "provider-selection-test-secret")
    action = approve_and_select_image(
        setup_batch, capsys, provider,
        api_config_path if provider == "third_party_api" else None,
    )

    assert action["kind"] == kind
    assert action["width"] == 2160
    assert action["height"] == 3840
    assert action["size"] == "2160x3840"
    assert action["native_resolution_required"] is True
    assert Path(action["prompt_path"]).name == "分镜提交提示词.txt"
    prompt = Path(action["prompt_path"]).read_text(encoding="utf-8")
    assert "【产品参考锁定】" in prompt
    assert "【原生输出参数】" in prompt
    assert action["reference_paths"]
    assert all(Path(path).is_file() for path in action["reference_paths"])
    if provider == "third_party_api":
        assert action["request_parameters"] == {"width": 2160, "height": 3840}
    else:
        assert "request_parameters" not in action


@pytest.mark.parametrize(
    ("dimensions", "passes"),
    [((2160, 3840), True), ((1080, 1920), False), ((1152, 2048), False), ((3840, 2160), False)],
)
def test_exact_image_dimensions_are_required_without_local_upscale(
    tmp_path, dimensions, passes
):
    runner = load_script("pipeline_runner.py")
    item = tmp_path / "V001_轻便_待生成"
    source = tmp_path / f"provider-{dimensions[0]}x{dimensions[1]}.png"
    Image.new("RGB", dimensions, "green").save(source)

    if passes:
        result = runner.accept_generated_image(item, "分镜图.png", source)
        assert result["size"] == [2160, 3840]
        assert Image.open(item / "分镜图.png").size == (2160, 3840)
        return

    with pytest.raises(ValueError, match="原生2160×3840|禁止本地放大"):
        runner.accept_generated_image(item, "分镜图.png", source)
    candidate = item / "_工作文件" / "生成过程" / "分镜候选.png"
    assert not candidate.exists()
    assert not (item / "分镜图.png").exists()


def test_third_party_image_action_exposes_key_environment_name_not_secret(
    setup_batch, capsys, api_config_path, monkeypatch
):
    secret = "provider-selection-test-secret"
    monkeypatch.setenv("EXAMPLE_IMAGE_API_KEY", secret)
    action = approve_and_select_image(setup_batch, capsys, "third_party_api", api_config_path)
    assert action["api_config"]["api_key_env"] == "EXAMPLE_IMAGE_API_KEY"
    assert secret not in json.dumps(action)
    _, _, batch, _ = setup_batch
    assert secret not in (batch / "流水线状态.json").read_text(encoding="utf-8")


def test_approved_manifest_rejects_a_later_image_provider_change(
    setup_batch, capsys, api_config_path
):
    approve_and_select_image(setup_batch, capsys, "gpt_web")
    runner, policy, batch, _ = setup_batch
    confirmation_path = batch / "启动确认单.json"
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    confirmation["image_provider"] = "third_party_api"
    confirmation["image_api_config"] = json.loads(api_config_path.read_text(encoding="utf-8"))
    confirmation_path.write_text(json.dumps(confirmation, ensure_ascii=False), encoding="utf-8")
    state = runner.load_or_create_state(batch, policy)
    with pytest.raises(PermissionError, match="清单|配置"):
        runner.validate_approved_manifest(batch, state)


def test_approved_manifest_rejects_a_later_api_config_change(
    setup_batch, capsys, api_config_path, monkeypatch
):
    monkeypatch.setenv("EXAMPLE_IMAGE_API_KEY", "provider-selection-test-secret")
    approve_and_select_image(setup_batch, capsys, "third_party_api", api_config_path)
    runner, policy, batch, _ = setup_batch
    confirmation_path = batch / "启动确认单.json"
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    confirmation["image_api_config"]["unit_price_yuan"] = "0.21"
    confirmation_path.write_text(json.dumps(confirmation, ensure_ascii=False), encoding="utf-8")

    state = runner.load_or_create_state(batch, policy)
    with pytest.raises(PermissionError, match="清单|配置"):
        runner.validate_approved_manifest(batch, state)


@pytest.mark.parametrize("command", ["next", "accept-image", "image-failed"])
def test_runner_rejects_provider_work_after_confirmation_changes(
    setup_batch, capsys, api_config_path, command
):
    action = approve_and_select_image(setup_batch, capsys, "gpt_web")
    runner, _, batch, _ = setup_batch
    confirmation_path = batch / "启动确认单.json"
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    confirmation["image_provider"] = "third_party_api"
    confirmation["image_api_config"] = json.loads(api_config_path.read_text(encoding="utf-8"))
    confirmation_path.write_text(json.dumps(confirmation, ensure_ascii=False), encoding="utf-8")
    if command == "next":
        args = ["next", "--batch", str(batch)]
    elif command == "accept-image":
        Image.new("RGB", (2160, 3840), "green").save(action["output_path"])
        args = [
            command, "--batch", str(batch), "--video-id", action["video_id"],
            "--artifact", action["artifact"], "--source", action["output_path"],
            "--action-id", action["action_id"],
        ]
    else:
        args = [
            command, "--batch", str(batch), "--video-id", action["video_id"],
            "--artifact", action["artifact"], "--reason", "provider changed",
            "--action-id", action["action_id"],
        ]
    assert runner.main(args) == 2
    assert "清单" in json.loads(capsys.readouterr().out)["reason"]


@pytest.mark.parametrize("provider", ["gpt_web", "third_party_api"])
def test_each_approved_provider_promotes_images_through_the_shared_accept_path(
    setup_batch, capsys, provider, api_config_path, monkeypatch
):
    monkeypatch.setenv("EXAMPLE_IMAGE_API_KEY", "provider-selection-test-secret")
    action = approve_and_select_image(
        setup_batch, capsys, provider,
        api_config_path if provider == "third_party_api" else None,
    )
    Image.new("RGB", (2160, 3840), "green").save(action["output_path"])
    runner, _, batch, item = setup_batch
    assert runner.main([
        "accept-image", "--batch", str(batch), "--video-id", action["video_id"],
        "--artifact", action["artifact"], "--source", action["output_path"],
        "--action-id", action["action_id"],
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["provider"] == provider
    assert (item / "分镜图.png").is_file()


@pytest.mark.parametrize("provider", ["gpt_web", "third_party_api"])
def test_provider_image_acceptance_uses_neutral_validation_audit_and_raw_evidence(
    setup_batch, capsys, provider, api_config_path, monkeypatch
):
    monkeypatch.setenv("EXAMPLE_IMAGE_API_KEY", "provider-selection-test-secret")
    action = approve_and_select_image(
        setup_batch, capsys, provider,
        api_config_path if provider == "third_party_api" else None,
    )
    assert Path(action["output_path"]).name == "生图原始分镜.png"
    Image.new("RGB", (2160, 3840), "green").save(action["output_path"])
    runner, _, batch, item = setup_batch
    assert runner.main([
        "accept-image", "--batch", str(batch), "--video-id", action["video_id"],
        "--artifact", action["artifact"], "--source", action["output_path"],
        "--action-id", action["action_id"],
    ]) == 0
    capsys.readouterr()
    audit = (item / "_工作文件" / "验收记录" / "产出验收记录.json").read_text(
        encoding="utf-8"
    )
    assert "生成图片结果按图片免审规则完成本地技术检查并自动晋升" in audit
    assert "GPT 网页结果" not in audit

    assert runner.main(["next", "--batch", str(batch)]) == 0
    failure_action = json.loads(capsys.readouterr().out)
    Image.new("RGB", (64, 64), "black").save(failure_action["output_path"])
    assert runner.main([
        "accept-image", "--batch", str(batch),
        "--video-id", failure_action["video_id"],
        "--artifact", failure_action["artifact"],
        "--source", failure_action["output_path"],
        "--action-id", failure_action["action_id"],
    ]) == 0
    failure = json.loads(capsys.readouterr().out)
    assert failure["kind"] == "IMAGE_FAILURE_RECORDED"
    assert "生成图片必须为原生2160×3840" in failure["reason"]
    assert "GPT 网页" not in failure["reason"]


def _approved_image_state(setup_batch, provider, api_config_path=None):
    runner, policy, batch, item = setup_batch
    confirmation_path = batch / "启动确认单.json"
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    confirmation["image_provider"] = provider
    confirmation["image_api_config"] = (
        json.loads(api_config_path.read_text(encoding="utf-8"))
        if api_config_path is not None else {}
    )
    confirmation_path.write_text(json.dumps(confirmation, ensure_ascii=False), encoding="utf-8")
    state = runner.RunnerState.new(runner._load_policy_module().policy_digest(policy))
    state.status = "RUNNING_AUTOMATICALLY"
    state.approved_budget = "10.00"
    state.estimated_v01_total = "3.00"
    state.approved_manifest = runner._confirmation_manifest(batch)
    state.manifest_digest = runner._load_policy_module().policy_digest(state.approved_manifest)
    runner.save_state(batch, state)
    return runner, policy, batch, state


@pytest.fixture
def api_batch(setup_batch, api_config_path, monkeypatch):
    monkeypatch.setenv("EXAMPLE_IMAGE_API_KEY", "provider-selection-test-secret")
    return _approved_image_state(setup_batch, "third_party_api", api_config_path)


@pytest.fixture
def web_batch(setup_batch):
    return _approved_image_state(setup_batch, "gpt_web")


def test_third_party_next_reserves_once_and_reuses_action(api_batch):
    runner, policy, batch, state = api_batch
    first = runner.next_action(batch, state, policy)
    second = runner.next_action(batch, state, policy)
    assert second == first
    assert state.image_budget_ledger[first["action_id"]]["status"] == "reserved"
    assert state.image_budget_ledger[first["action_id"]]["cost"] == "0.20"
    assert len(state.image_budget_ledger) == 1


def test_gpt_web_never_touches_image_api_ledger(web_batch):
    runner, policy, batch, state = web_batch
    assert runner.next_action(batch, state, policy)["kind"] == "GPT_WEB_IMAGE_REQUIRED"
    assert state.image_budget_ledger == {}


def test_image_prompt_preflight_failure_reserves_no_external_action(web_batch):
    runner, policy, batch, state = web_batch
    product = Path(json.loads(
        (batch / "启动确认单.json").read_text(encoding="utf-8")
    )["product_images"][0])
    product.unlink()

    action = runner.next_action(batch, state, policy)

    assert action["kind"] == "CONTENT_PREFLIGHT_FAILED"
    assert action["video_id"] == "V001"
    assert "图片提交提示词预检失败：image.reference_missing" in action["reason"]
    assert state.model_actions == {}
    assert state.pending_action is None


def test_old_runner_state_without_image_api_ledger_loads_empty(setup_batch):
    runner, policy, batch, _ = setup_batch
    state = runner.RunnerState.new(runner._load_policy_module().policy_digest(policy))
    runner.save_state(batch, state)
    state_path = batch / "流水线状态.json"
    serialized = json.loads(state_path.read_text(encoding="utf-8"))
    serialized.pop("image_budget_ledger")
    state_path.write_text(json.dumps(serialized), encoding="utf-8")

    assert runner.load_or_create_state(batch, policy).image_budget_ledger == {}


def test_generic_reservation_rejects_third_party_image_category(api_batch):
    runner, policy, batch, state = api_batch

    with pytest.raises(ValueError, match="third_party_api"):
        runner._reserve_action(
            batch, state, policy,
            {"kind": "THIRD_PARTY_IMAGE_REQUIRED", "video_id": "V001", "artifact": "分镜图.png"},
            "third_party_api_image",
        )


def settle_valid_image(runner, batch, action):
    Image.new("RGB", (2160, 3840), "green").save(action["output_path"])
    return runner.main([
        "accept-image", "--batch", str(batch), "--video-id", action["video_id"],
        "--artifact", action["artifact"], "--source", action["output_path"],
        "--action-id", action["action_id"],
    ])


def test_api_budget_exhaustion_emits_no_new_paid_action(api_batch, capsys):
    runner, policy, batch, state = api_batch
    confirmation_path = batch / "启动确认单.json"
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    confirmation["max_budget_yuan"] = "3.20"
    confirmation_path.write_text(json.dumps(confirmation, ensure_ascii=False), encoding="utf-8")
    state.approved_manifest = runner._confirmation_manifest(batch)
    state.manifest_digest = runner._load_policy_module().policy_digest(state.approved_manifest)
    state.approved_budget = "3.20"
    first = runner.next_action(batch, state, policy)
    assert settle_valid_image(runner, batch, first) == 0
    capsys.readouterr()
    state = runner.load_or_create_state(batch, policy)
    assert state.image_budget_ledger[first["action_id"]]["status"] == "spent"
    action = runner.next_action(batch, state, policy)
    assert action["kind"] == "BLOCKED"
    assert "图片 API" in action["reason"] and "预算" in action["reason"]


@pytest.mark.parametrize(
    ("submission_state", "expected"),
    [("not_sent", "released"), ("sent", "spent"), ("unknown", "unknown")],
)
def test_third_party_failure_settles_once_by_submission_state(
    api_batch, capsys, submission_state, expected
):
    runner, policy, batch, state = api_batch
    action = runner.next_action(batch, state, policy)
    args = [
        "image-failed", "--batch", str(batch), "--video-id", action["video_id"],
        "--artifact", action["artifact"], "--reason", "provider failed",
        "--action-id", action["action_id"], "--submission-state", submission_state,
    ]
    assert runner.main(args) == 0
    settled = runner.load_or_create_state(batch, policy)
    assert settled.image_budget_ledger[action["action_id"]]["status"] == expected
    assert runner.main(args) == 0
    again = runner.load_or_create_state(batch, policy)
    assert again.image_budget_ledger[action["action_id"]]["status"] == expected
    if submission_state == "unknown":
        assert again.status == "BLOCKED"
        assert action["action_id"] in again.model_actions
        assert action["action_id"] in again.image_budget_ledger
        assert runner.next_action(batch, again, policy)["kind"] == "BLOCKED"


def test_third_party_failure_rejects_same_reason_with_contradictory_submission_state(
    api_batch, capsys
):
    runner, policy, batch, state = api_batch
    action = runner.next_action(batch, state, policy)
    base_args = [
        "image-failed", "--batch", str(batch), "--video-id", action["video_id"],
        "--artifact", action["artifact"], "--reason", "provider failed",
        "--action-id", action["action_id"],
    ]
    assert runner.main([*base_args, "--submission-state", "sent"]) == 0
    capsys.readouterr()

    assert runner.main([*base_args, "--submission-state", "unknown"]) == 2
    assert "其他结果" in json.loads(capsys.readouterr().out)["reason"]
    restored = runner.load_or_create_state(batch, policy)
    assert restored.image_budget_ledger[action["action_id"]]["status"] == "spent"


def test_gpt_web_failure_replays_same_reason_across_submission_states(web_batch, capsys):
    runner, policy, batch, state = web_batch
    action = runner.next_action(batch, state, policy)
    base_args = [
        "image-failed", "--batch", str(batch), "--video-id", action["video_id"],
        "--artifact", action["artifact"], "--reason", "browser failed",
        "--action-id", action["action_id"],
    ]
    assert runner.main([*base_args, "--submission-state", "sent"]) == 0
    capsys.readouterr()

    assert runner.main([*base_args, "--submission-state", "unknown"]) == 0
    assert runner.load_or_create_state(batch, policy).image_budget_ledger == {}


def test_gpt_web_legacy_reason_digest_failure_receipt_replays(web_batch, capsys):
    runner, policy, batch, state = web_batch
    action = runner.next_action(batch, state, policy)
    reason = "legacy browser failure"
    expected_result = {
        "kind": "IMAGE_FAILURE_RECORDED",
        "retry_pending": True,
        "video_id": action["video_id"],
        "artifact": action["artifact"],
        "reason": reason,
    }
    row = state.model_actions[action["action_id"]]
    row.update({
        "status": "failed",
        "input_digest": hashlib.sha256(reason.encode()).hexdigest(),
        "result": expected_result,
        "completed_at": "2026-09-09T00:00:00+00:00",
    })
    state.pending_action = None
    runner.save_state(batch, state)

    assert runner.main([
        "image-failed", "--batch", str(batch), "--video-id", action["video_id"],
        "--artifact", action["artifact"], "--reason", reason,
        "--action-id", action["action_id"], "--submission-state", "unknown",
    ]) == 0
    assert json.loads(capsys.readouterr().out) == expected_result
    restored = runner.load_or_create_state(batch, policy)
    assert restored.model_actions[action["action_id"]]["input_digest"] == (
        hashlib.sha256(reason.encode()).hexdigest()
    )
