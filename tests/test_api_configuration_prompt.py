"""Regression tests for the read-only API configuration first response."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "skill-package"
    / "product-video-pipeline"
    / "scripts"
    / "api_config.py"
)
SPEC = importlib.util.spec_from_file_location("product_video_api_config", SCRIPT_PATH)
assert SPEC and SPEC.loader
api_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api_config)


def test_configuration_prompt_reports_masked_status_and_fixed_choices() -> None:
    payload = api_config.status_payload(
        api_config.MemoryStore(
            {
                "AUTODL_API_KEY": "autodl-secret-1234",
                "AUTODL_AUTH_SCHEME": "bearer",
                "PRODUCT_VIDEO_IMAGE_API_KEY": "image-secret-5678",
            }
        )
    )

    prompt = api_config.format_configuration_prompt(payload)

    category_lines = [line for line in prompt.splitlines() if " API（" in line]
    assert category_lines == [
        "AutoDL.Art 视频 API（必需）：已配置，密钥 ****1234",
        "第三方生图 API（可选）：未配置，密钥 ****5678",
        "第三方文本生成 API（可选）：未配置，密钥 未配置",
    ]
    assert len(category_lines) == 3
    assert "已配置" in category_lines[0]
    assert "未配置" in category_lines[1]
    assert "未配置" in category_lines[2]
    assert "****1234" in prompt
    assert "****5678" in prompt
    assert "autodl-secret-1234" not in prompt
    assert "image-secret-5678" not in prompt
    assert "本机 Codex 和 ChatGPT 网页端使用登录状态，不需要配置 API；MiniMax-H3 视频统一通过 AutoDL.Art。" in prompt
    assert "Recommended" not in prompt
    assert "GPT Image API" not in prompt
    assert "配置 MiniMax API" not in prompt


class FailingStore:
    def get(self, name: str) -> None:
        raise OSError("secret-canary")


class ReadOnlyStore:
    def __init__(self) -> None:
        self.set_many_called = False

    def get(self, name: str) -> str | None:
        return {
            "AUTODL_API_KEY": "prompt-secret-9012",
            "AUTODL_AUTH_SCHEME": "bearer",
        }.get(name)

    def set_many(self, values: object) -> None:
        self.set_many_called = True
        raise AssertionError("prompt must not write configuration")


def test_prompt_command_reads_status_without_writing(monkeypatch, capsys) -> None:
    store = ReadOnlyStore()
    monkeypatch.setattr(api_config, "WindowsUserEnvironmentStore", lambda: store)

    assert api_config.main(["prompt"]) == 0

    captured = capsys.readouterr()
    assert "当前 API 配置状态：" in captured.out
    assert "****9012" in captured.out
    assert "prompt-secret-9012" not in captured.out
    assert captured.err == ""
    assert not store.set_many_called


def test_prompt_command_hides_status_read_errors(monkeypatch, capsys) -> None:
    monkeypatch.setattr(api_config, "WindowsUserEnvironmentStore", FailingStore)

    assert api_config.main(["prompt"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "无法读取当前配置状态，永久配置未更改"
    assert "secret-canary" not in captured.err
