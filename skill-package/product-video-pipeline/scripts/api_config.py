#!/usr/bin/env python3
"""Safely configure persistent API settings for product-video-pipeline on Windows."""

from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from typing import Dict, Mapping, MutableMapping, Optional, Sequence
from urllib.parse import urlparse

try:
    import winreg
except ImportError:  # pragma: no cover - Windows is the supported persistence target.
    winreg = None


CONFIG_SCHEMAS = {
    "autodl": ("AUTODL_API_KEY", "AUTODL_AUTH_SCHEME"),
    "image": (
        "PRODUCT_VIDEO_IMAGE_API_PROVIDER",
        "PRODUCT_VIDEO_IMAGE_API_BASE_URL",
        "PRODUCT_VIDEO_IMAGE_API_MODEL",
        "PRODUCT_VIDEO_IMAGE_API_KEY",
        "PRODUCT_VIDEO_IMAGE_API_UNIT_PRICE_YUAN",
    ),
    "text": (
        "PRODUCT_VIDEO_TEXT_API_PROVIDER",
        "PRODUCT_VIDEO_TEXT_API_BASE_URL",
        "PRODUCT_VIDEO_TEXT_API_MODEL",
        "PRODUCT_VIDEO_TEXT_API_KEY",
    ),
}

CATEGORY_META = {
    "autodl": {"name": "AutoDL.Art 视频 API", "requirement": "必需", "key": "AUTODL_API_KEY"},
    "image": {
        "name": "第三方生图 API",
        "requirement": "可选",
        "key": "PRODUCT_VIDEO_IMAGE_API_KEY",
    },
    "text": {
        "name": "第三方文本生成 API",
        "requirement": "可选",
        "key": "PRODUCT_VIDEO_TEXT_API_KEY",
    },
}


class ConfigurationInputError(ValueError):
    """Validation error whose message is safe to show to the user."""


class PersistenceRollbackError(RuntimeError):
    """Persistence failed and the previous configuration could not be restored."""


def mask_secret(value: Optional[str]) -> str:
    if not value:
        return "未配置"
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]


def _validate_environment_value(name: str, value: Optional[str]) -> None:
    if value is None:
        return
    if "\x00" in name or "\x00" in value:
        raise ConfigurationInputError("环境变量名称和值不能包含 NUL 字符")
    if len(name) + 1 + len(value) > 32767:
        raise ConfigurationInputError(f"环境变量过长：{name}")


class MemoryStore:
    """In-memory store used by offline self-tests."""

    def __init__(self, values: Optional[Mapping[str, Optional[str]]] = None):
        self.values: MutableMapping[str, str] = {
            key: value for key, value in (values or {}).items() if value is not None
        }

    def get(self, name: str) -> Optional[str]:
        return self.values.get(name)

    def set_many(self, values: Mapping[str, Optional[str]]) -> None:
        updated = dict(self.values)
        for name, value in values.items():
            if value is None:
                updated.pop(name, None)
            else:
                updated[name] = value
        self.values = updated


class WindowsUserEnvironmentStore:
    """Windows HKCU Environment store with best-effort change notification."""

    registry_path = "Environment"

    def _require_windows(self) -> None:
        if winreg is None or os.name != "nt":
            raise RuntimeError("永久 API 配置仅支持 Windows 当前用户环境变量")

    def get(self, name: str) -> Optional[str]:
        self._require_windows()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_path) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return None
        return str(value) if value is not None else None

    def set_many(self, values: Mapping[str, Optional[str]]) -> None:
        self._require_windows()
        for name, value in values.items():
            _validate_environment_value(name, value)
        previous_registry = {name: self.get(name) for name in values}
        previous_environment = {name: os.environ.get(name) for name in values}
        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                self.registry_path,
                0,
                winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
            ) as key:
                for name, value in values.items():
                    if value is None:
                        try:
                            winreg.DeleteValue(key, name)
                        except FileNotFoundError:
                            pass
                    else:
                        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            for name, value in values.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        except Exception as exc:
            try:
                self._restore(previous_registry)
                self._restore_process_environment(previous_environment)
            except Exception as rollback_error:
                raise PersistenceRollbackError("API 配置写入失败，且旧值恢复失败") from rollback_error
            raise exc
        self._broadcast_change()

    def _restore(self, previous: Mapping[str, Optional[str]]) -> None:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            self.registry_path,
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            for name, value in previous.items():
                if value is None:
                    try:
                        winreg.DeleteValue(key, name)
                    except FileNotFoundError:
                        pass
                else:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    @staticmethod
    def _restore_process_environment(previous: Mapping[str, Optional[str]]) -> None:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    @staticmethod
    def _broadcast_change() -> None:
        try:
            result = ctypes.c_ulong()
            ctypes.windll.user32.SendMessageTimeoutW(
                0xFFFF,
                0x001A,
                0,
                "Environment",
                0x0002,
                5000,
                ctypes.byref(result),
            )
        except (AttributeError, OSError):
            pass


def _validate_https_url(value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(ord(character) < 32 for character in value)
    ):
        raise ConfigurationInputError("base_url 必须是有效的 https:// 地址")


def validate_category_values(category: str, values: Mapping[str, str]) -> None:
    if category not in CONFIG_SCHEMAS:
        raise ConfigurationInputError("未知 API 类型")
    missing = [name for name in CONFIG_SCHEMAS[category] if not values.get(name, "").strip()]
    if missing:
        raise ConfigurationInputError("缺少配置字段：" + ", ".join(missing))
    if category == "autodl":
        if values["AUTODL_AUTH_SCHEME"] not in {"bearer", "raw"}:
            raise ConfigurationInputError("AUTODL_AUTH_SCHEME 只能是 bearer 或 raw")
    else:
        _validate_https_url(values[f"PRODUCT_VIDEO_{category.upper()}_API_BASE_URL"])
        if category == "image":
            try:
                price = Decimal(values["PRODUCT_VIDEO_IMAGE_API_UNIT_PRICE_YUAN"])
            except (InvalidOperation, ValueError) as exc:
                raise ConfigurationInputError("生图 API 单张价格必须是有效正数") from exc
            if not price.is_finite() or price <= 0:
                raise ConfigurationInputError("生图 API 单张价格必须是有效正数")


def save_category(category: str, values: Mapping[str, str], store) -> None:
    validate_category_values(category, values)
    schema = CONFIG_SCHEMAS[category]
    selected = {name: values[name].strip() for name in schema}
    previous = {name: store.get(name) for name in schema}
    try:
        store.set_many(selected)
    except Exception:
        try:
            store.set_many(previous)
        except Exception as rollback_error:
            raise PersistenceRollbackError("配置写入失败，且旧值恢复失败") from rollback_error
        raise


def get_config_value(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value:
        return value
    if os.name != "nt" or winreg is None:
        return None
    return WindowsUserEnvironmentStore().get(name)


def image_api_runtime_config(store=None) -> Dict[str, str]:
    store = store or WindowsUserEnvironmentStore()
    values = {name: store.get(name) for name in CONFIG_SCHEMAS["image"]}
    validate_category_values("image", {name: value or "" for name, value in values.items()})
    return {
        "api_name": str(values["PRODUCT_VIDEO_IMAGE_API_PROVIDER"]),
        "base_url": str(values["PRODUCT_VIDEO_IMAGE_API_BASE_URL"]),
        "model": str(values["PRODUCT_VIDEO_IMAGE_API_MODEL"]),
        "api_key_env": "PRODUCT_VIDEO_IMAGE_API_KEY",
        "unit_price_yuan": str(values["PRODUCT_VIDEO_IMAGE_API_UNIT_PRICE_YUAN"]),
    }


def status_payload(store=None) -> Dict[str, object]:
    store = store or WindowsUserEnvironmentStore()
    result: Dict[str, object] = {}
    for category, schema in CONFIG_SCHEMAS.items():
        values = {name: store.get(name) for name in schema}
        key_name = CATEGORY_META[category]["key"]
        public_values = {}
        for name, value in values.items():
            if name == key_name or not value:
                continue
            if name.endswith("_BASE_URL"):
                parsed = urlparse(value)
                if (
                    parsed.username is not None
                    or parsed.password is not None
                    or parsed.query
                    or parsed.fragment
                    or any(ord(character) < 32 for character in value)
                ):
                    public_values[name] = "[已隐藏：URL 含敏感内容]"
                    continue
            public_values[name] = value
        result[category] = {
            "name": CATEGORY_META[category]["name"],
            "requirement": CATEGORY_META[category]["requirement"],
            "status": "已配置" if all(values.get(name) for name in schema) else "未配置",
            "api_key": mask_secret(values.get(key_name)),
            "settings": public_values,
        }
    return result


def format_status(payload: Mapping[str, object]) -> str:
    lines = []
    for value in payload.values():
        lines.append(
            f"{value['name']}（{value['requirement']}）："
            f"{value['status']}，密钥 {value['api_key']}"
        )
        for name, setting in value.get("settings", {}).items():
            lines.append(f"  {name}={setting}")
    return "\n".join(lines)


def format_configuration_prompt(payload: Mapping[str, object]) -> str:
    status = format_status(payload)
    return (
        "当前 API 配置状态：\n\n"
        f"{status}\n\n"
        "本机 Codex 和 ChatGPT 网页端使用登录状态，不需要配置 API；"
        "MiniMax-H3 视频统一通过 AutoDL.Art。\n\n"
        "请选择本次需要配置或更换的一项：\n"
        "AutoDL.Art 视频 API / 第三方生图 API / 第三方文本生成 API"
    )


def format_error(exc: Exception) -> str:
    if isinstance(exc, ConfigurationInputError):
        return f"配置失败：{exc}"
    if isinstance(exc, PersistenceRollbackError):
        return "配置失败：写入和回滚均失败，配置状态可能不一致，需要检查"
    if isinstance(exc, ValueError):
        return "配置失败：配置内容无效"
    return "配置失败：无法写入永久环境变量，原配置已保留"


def _prompt_with_current(label: str, current: Optional[str]) -> str:
    suffix = f" [{current}]" if current else ""
    value = input(f"{label}{suffix}：").strip()
    return value or (current or "")


def _prompt_secret(label: str, current: Optional[str]) -> str:
    hint = f"（回车保留 {mask_secret(current)}）" if current else ""
    value = getpass.getpass(f"{label}{hint}：").strip()
    return value or (current or "")


def prompt_category_values(category: str, store) -> Dict[str, str]:
    if category == "autodl":
        return {
            "AUTODL_API_KEY": _prompt_secret("AutoDL API Key", store.get("AUTODL_API_KEY")),
            "AUTODL_AUTH_SCHEME": _prompt_with_current(
                "鉴权格式 bearer/raw", store.get("AUTODL_AUTH_SCHEME") or "bearer"
            ),
        }
    prefix = f"PRODUCT_VIDEO_{category.upper()}_API"
    label = "生图" if category == "image" else "文本"
    values = {
        f"{prefix}_PROVIDER": _prompt_with_current(
            f"第三方{label}服务商", store.get(f"{prefix}_PROVIDER")
        ),
        f"{prefix}_BASE_URL": _prompt_with_current(
            "HTTPS base_url", store.get(f"{prefix}_BASE_URL")
        ),
        f"{prefix}_MODEL": _prompt_with_current("模型名称", store.get(f"{prefix}_MODEL")),
        f"{prefix}_KEY": _prompt_secret("API Key", store.get(f"{prefix}_KEY")),
    }
    if category == "image":
        values[f"{prefix}_UNIT_PRICE_YUAN"] = _prompt_with_current(
            "单张价格（元）", store.get(f"{prefix}_UNIT_PRICE_YUAN")
        )
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="产品视频技能 API 永久配置工具")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status", help="显示已遮罩的 API 配置状态")
    status.add_argument("--json", action="store_true", help="输出 JSON 状态")
    subparsers.add_parser("prompt", help="输出固定 API 配置首轮回复")
    configure = subparsers.add_parser("configure", help="通过隐藏输入配置或更换一个 API")
    configure.add_argument("--category", choices=tuple(CONFIG_SCHEMAS), required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    store = WindowsUserEnvironmentStore()
    try:
        if args.command == "prompt":
            try:
                payload = status_payload(store)
            except Exception:
                print("无法读取当前配置状态，永久配置未更改", file=sys.stderr)
                return 1
            print(format_configuration_prompt(payload))
            return 0
        if args.command == "status":
            payload = status_payload(store)
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(format_status(payload))
            return 0
        values = prompt_category_values(args.category, store)
        save_category(args.category, values, store)
        category_status = status_payload(store)[args.category]
        print(
            json.dumps(
                {
                    "result": "配置已永久保存到 Windows 当前用户环境变量",
                    "validation": "已完成本地格式检查；未执行联网或计费验证",
                    "category": category_status,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (EOFError, KeyboardInterrupt):
        print("配置已取消，原配置保持不变", file=sys.stderr)
        return 130
    except (OSError, RuntimeError, ValueError) as exc:
        print(format_error(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
