#!/usr/bin/env python3
"""Portable AutoDL.Art MiniMax-H3 ComfyUI workflow client.

The submit payload is supplied as JSON because AutoDL can revise model fields.
The user must confirm the live API schema, price, and budget at batch startup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


COMFYUI_WORKFLOW_BASE = "https://www.autodl.art/api/v1/comfyui/comfyui_workflow"
WORKFLOW_ID = "minimax_h3_lightx2v_v5_15s"
KNOWN_WORKFLOW_IDS = (
    WORKFLOW_ID,
    "minimax_h3_lightx2v",
)
QUERY_URL_TEMPLATE = "https://www.autodl.art/api/v1/comfyui/comfyui_workflow/result/{task_id}"


def extract_task_id(response: Dict[str, object]) -> str:
    task_id = response.get("task_id")
    if not task_id and isinstance(response.get("data"), dict):
        task_id = response["data"].get("task_id")
    if not task_id:
        raise ValueError("AutoDL 响应中没有 task_id")
    return str(task_id)


def _request_hash(payload: Dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _authorization(api_key: str, auth_scheme: str) -> str:
    if auth_scheme == "raw":
        return api_key
    if auth_scheme == "bearer":
        return f"Bearer {api_key}"
    raise ValueError("auth_scheme 只能是 bearer 或 raw")


def validate_first_last_payload(payload: Dict[str, object]) -> None:
    required = ("prompt", "duration", "resolution", "first_frame", "last_frame")
    missing = [field for field in required if not payload.get(field)]
    if missing:
        raise ValueError("首尾帧 payload 缺少字段：" + ", ".join(missing))
    if payload["duration"] != 15:
        raise ValueError("首尾帧视频 duration 必须为 15")
    if payload["first_frame"] == payload["last_frame"]:
        raise ValueError("last_frame 必须独立生成，不得复用 first_frame")
    prompt = str(payload["prompt"])
    required_rules = ("一镜到底", "连续平稳运镜", "完整双人对话口播")
    missing_rules = [rule for rule in required_rules if rule not in prompt]
    if missing_rules:
        raise ValueError("prompt 缺少全程规则：" + ", ".join(missing_rules))


def _json_request(
    method: str,
    url: str,
    api_key: str,
    auth_scheme: str,
    payload: Optional[Dict[str, object]] = None,
    timeout: int = 60,
) -> Dict[str, object]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": _authorization(api_key, auth_scheme),
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"AutoDL HTTP {exc.code}；请检查鉴权、余额、端点和请求参数") from exc
    except URLError as exc:
        raise RuntimeError(f"AutoDL 网络错误：{exc.reason}") from exc


def submit_payload(
    payload_path: Path,
    *,
    api_key: Optional[str] = None,
    auth_scheme: str = "bearer",
    dry_run: bool = False,
    confirm_paid: bool = False,
    workflow_id: str = WORKFLOW_ID,
    timeout: int = 60,
) -> Dict[str, object]:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("提交 payload 必须是 JSON 对象")
    if workflow_id not in KNOWN_WORKFLOW_IDS:
        raise ValueError(f"不支持的工作流 ID：{workflow_id}")
    validate_first_last_payload(payload)
    submit_url = f"{COMFYUI_WORKFLOW_BASE}/{workflow_id}"
    preview = {
        "dry_run": dry_run,
        "url": submit_url,
        "request_hash": _request_hash(payload),
        "payload": payload,
    }
    if dry_run:
        return preview
    if not confirm_paid:
        raise PermissionError("这是付费操作；必须显式传入 confirm_paid=True")
    api_key = api_key or os.environ.get("AUTODL_API_KEY")
    if not api_key:
        raise ValueError("未设置 AUTODL_API_KEY")
    response = _json_request("POST", submit_url, api_key, auth_scheme, payload, timeout)
    return {
        **preview,
        "dry_run": False,
        "task_id": extract_task_id(response),
        "request_id": response.get("request_id") or (response.get("data") or {}).get("request_id"),
        "response": response,
    }


def query_task(
    task_id: str,
    *,
    api_key: Optional[str] = None,
    auth_scheme: str = "bearer",
    timeout: int = 60,
) -> Dict[str, object]:
    api_key = api_key or os.environ.get("AUTODL_API_KEY")
    if not api_key:
        raise ValueError("未设置 AUTODL_API_KEY")
    return _json_request(
        "GET",
        QUERY_URL_TEMPLATE.format(task_id=task_id),
        api_key,
        auth_scheme,
        timeout=timeout,
    )


def _task_data(response: Dict[str, object]) -> Dict[str, object]:
    return response["data"] if isinstance(response.get("data"), dict) else response


def _status(response: Dict[str, object]) -> str:
    return str(_task_data(response).get("status", "unknown")).lower()


def poll_task(
    task_id: str,
    *,
    api_key: Optional[str] = None,
    auth_scheme: str = "bearer",
    interval_seconds: int = 20,
    max_wait_seconds: int = 3600,
    network_retries: int = 5,
) -> Dict[str, object]:
    started = time.monotonic()
    errors = 0
    while time.monotonic() - started < max_wait_seconds:
        try:
            response = query_task(task_id, api_key=api_key, auth_scheme=auth_scheme)
            errors = 0
        except RuntimeError:
            errors += 1
            if errors > network_retries:
                raise
            time.sleep(min(interval_seconds, 5 * errors))
            continue
        status = _status(response)
        if status in {"success", "succeeded", "completed", "failed", "cancelled", "canceled"}:
            return response
        time.sleep(interval_seconds)
    return {"task_id": task_id, "status": "poll_timeout"}


def first_result_url(response: Dict[str, object]) -> str:
    data = _task_data(response)
    for key in ("video_url", "url", "download_url"):
        if data.get(key):
            return str(data[key])
    results = data.get("results", [])
    if isinstance(results, list):
        for result in results:
            if isinstance(result, str) and result.startswith("http"):
                return result
            if isinstance(result, dict):
                for key in ("url", "video_url", "download_url"):
                    if result.get(key):
                        return str(result[key])
    raise ValueError("成功响应中没有可下载的视频 URL")


def download_atomic(url: str, output: Path, retries: int = 4, timeout: int = 180) -> Path:
    output = output.resolve()
    partial = output.with_suffix(output.suffix + ".part")
    output.parent.mkdir(parents=True, exist_ok=True)
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            request = Request(url, headers={"User-Agent": "product-video-pipeline/1.0"})
            with urlopen(request, timeout=timeout) as response, partial.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            if partial.stat().st_size <= 0:
                raise RuntimeError("下载文件为空")
            partial.replace(output)
            return output
        except (OSError, URLError, RuntimeError) as exc:
            last_error = exc
            if partial.exists():
                partial.unlink()
            if attempt < retries:
                time.sleep(min(10, attempt * 2))
    raise RuntimeError(f"下载失败，已尝试 {retries} 次：{last_error}")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AutoDL.Art MiniMax-H3 ComfyUI 工作流便携客户端")
    parser.add_argument("--auth-scheme", choices=("bearer", "raw"), default=os.environ.get("AUTODL_AUTH_SCHEME", "bearer"))
    sub = parser.add_subparsers(dest="command", required=True)

    submit = sub.add_parser("submit")
    submit.add_argument("--payload", type=Path, required=True)
    submit.add_argument("--workflow-id", choices=KNOWN_WORKFLOW_IDS, default=WORKFLOW_ID)
    submit.add_argument("--dry-run", action="store_true")
    submit.add_argument("--confirm-paid", choices=("YES",))
    submit.add_argument("--state", type=Path)

    query = sub.add_parser("query")
    query.add_argument("--task-id", required=True)

    poll = sub.add_parser("poll")
    poll.add_argument("--task-id", required=True)
    poll.add_argument("--interval", type=int, default=20)
    poll.add_argument("--max-wait", type=int, default=3600)
    poll.add_argument("--state", type=Path)

    download = sub.add_parser("download")
    download.add_argument("--url", required=True)
    download.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "submit":
            result = submit_payload(
                args.payload,
                auth_scheme=args.auth_scheme,
                dry_run=args.dry_run,
                confirm_paid=args.confirm_paid == "YES",
                workflow_id=args.workflow_id,
            )
            if args.state:
                _write_json(args.state, result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "query":
            print(json.dumps(query_task(args.task_id, auth_scheme=args.auth_scheme), ensure_ascii=False, indent=2))
        elif args.command == "poll":
            result = poll_task(
                args.task_id,
                auth_scheme=args.auth_scheme,
                interval_seconds=args.interval,
                max_wait_seconds=args.max_wait,
            )
            if args.state:
                _write_json(args.state, result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "download":
            print(download_atomic(args.url, args.output))
        return 0
    except (OSError, ValueError, PermissionError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
