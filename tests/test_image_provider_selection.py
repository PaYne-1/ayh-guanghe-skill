import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


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


@pytest.mark.parametrize("provider", ["gpt_web", "third_party_api"])
def test_policy_accepts_exactly_two_image_providers(provider):
    policy = load_script("pipeline_policy.py")
    assert policy.normalize_image_provider(provider) == provider


def test_third_party_config_requires_non_secret_fields():
    policy = load_script("pipeline_policy.py")
    valid = {
        "api_name": "Example Images",
        "base_url": "https://images.example.test/v1",
        "model": "image-v1",
        "api_key_env": "EXAMPLE_IMAGE_API_KEY",
        "unit_price_yuan": "0.20",
        "batch_budget_yuan": "5.00",
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

    config = {
        "api_name": "Example Images",
        "base_url": "https://images.example.test/v1",
        "model": "image-v1",
        "api_key_env": "EXAMPLE_IMAGE_API_KEY",
        "unit_price_yuan": "0.20",
        "batch_budget_yuan": "5.00",
    }
    api_context = workflow.initialize_batch(
        **{**initialization_kwargs, "now": datetime(2026, 9, 10, tzinfo=timezone.utc)},
        image_provider="third_party_api",
        image_api_config=config,
    )
    api_confirmation = json.loads((api_context.batch_dir / "启动确认单.json").read_text(encoding="utf-8"))
    assert api_confirmation["image_provider"] == "third_party_api"
    assert api_confirmation["image_api_config"] == config


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
        "batch_budget_yuan": "5.00",
    }
    config_path = initialization_kwargs["knowledge_dir"].parent / "image-api-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    assert workflow.main([
        *base_args,
        "--image-provider", "third_party_api",
        "--image-api-config", str(config_path),
    ]) == 0
