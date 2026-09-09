# Hermes 本地 Qwen 部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Windows 本机部署可由 Hermes 调用的 Qwen 服务，保留 DeepSeek 回退，并用非付费方式验证 `ayh-h3` 技能执行能力。

**Architecture:** Ollama 在仅限环回地址的已登记 AI 端口上提供 OpenAI 兼容接口，加载 `qwen3.5:9b` 并固定 65536 上下文、单并发和量化 KV Cache。Hermes 通过命名自定义提供商 `custom:local-qwen` 接入，不覆盖现有 DeepSeek 配置；项目脚本负责启动、停止、健康检查和配置审计。

**Tech Stack:** Windows 11、PowerShell 7.6、Python 3.9 标准库、Ollama、Qwen3.5 9B、Hermes Agent、OpenAI Chat Completions API、Git。

## Global Constraints

- 新项目固定创建在 `D:\0-AI 项目\本地Qwen推理服务`，技术内部标识固定为 `local-qwen-service`。
- 创建项目前必须读取 `C:\Users\Administrator\.codex\PORT_REGISTRY.json`，从 `7001-7199` 选取最小的未登记且未占用端口，并立即登记为 `aiPort`。
- Ollama 只监听 `127.0.0.1`，不得向局域网或公网开放。
- 模型固定从 Ollama 官方模型库拉取 `qwen3.5:9b`；不得静默替换成第三方模型。
- Ollama 与 Hermes 的上下文均固定为 `65536`，服务并发固定为 `1`。
- 现有 DeepSeek 配置和密钥必须保留；任何输出、日志或提交都不得包含 API Key。
- 所有 AutoDL 验证只允许本地 `--dry-run` 或技能自测，不得提交付费任务。
- 在 Qwen 连续通过工具调用与技能回归前，不得把 DeepSeek 从 Hermes 配置中删除。
- 每项文件修改遵循先测试失败、再最小实现、再测试通过的顺序。

---

### Task 1: 创建项目并原子登记 AI 服务端口

**Files:**
- Create: `D:\0-AI 项目\本地Qwen推理服务\tests\test_project_contract.py`
- Create: `D:\0-AI 项目\本地Qwen推理服务\config\service.json`
- Create: `D:\0-AI 项目\本地Qwen推理服务\PROJECT_INFO.md`
- Create: `D:\0-AI 项目\本地Qwen推理服务\README.md`
- Modify: `C:\Users\Administrator\.codex\PORT_REGISTRY.json`

**Interfaces:**
- Consumes: 端口登记表 JSON 与 Windows 当前 TCP 监听端口。
- Produces: `config/service.json`，字段为 `host: str`、`port: int`、`baseUrl: str`、`model: str`、`contextLength: int`、`parallel: int`、`kvCacheType: str`。

- [ ] **Step 1: 创建项目目录和 Git 仓库**

```powershell
$projectRoot = 'D:\0-AI 项目\本地Qwen推理服务'
New-Item -ItemType Directory -Force -Path $projectRoot, "$projectRoot\config", "$projectRoot\scripts", "$projectRoot\tests", "$projectRoot\logs", "$projectRoot\run" | Out-Null
git -C $projectRoot init -b main
```

Expected: `Initialized empty Git repository in D:/0-AI 项目/本地Qwen推理服务/.git/`。

- [ ] **Step 2: 写入失败的项目契约测试**

```python
# tests/test_project_contract.py
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY = pathlib.Path(r"C:\Users\Administrator\.codex\PORT_REGISTRY.json")


class ProjectContractTest(unittest.TestCase):
    def test_service_config_and_registry_agree(self):
        service = json.loads((ROOT / "config" / "service.json").read_text(encoding="utf-8"))
        registry = json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
        self.assertEqual(service["host"], "127.0.0.1")
        self.assertTrue(7001 <= service["port"] <= 7199)
        self.assertEqual(service["baseUrl"], f'http://127.0.0.1:{service["port"]}/v1')
        self.assertEqual(service["model"], "qwen3.5:9b")
        self.assertEqual(service["contextLength"], 65536)
        self.assertEqual(service["parallel"], 1)
        self.assertEqual(service["kvCacheType"], "q8_0")
        matches = [p for p in registry["projects"] if p.get("techId") == "local-qwen-service"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["aiPort"], service["port"])

    def test_required_project_info_exists(self):
        text = (ROOT / "PROJECT_INFO.md").read_text(encoding="utf-8")
        for required in ("本地Qwen推理服务", str(ROOT), "local-qwen-service", "是否固定端口：是"):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 运行测试并确认因配置缺失而失败**

Run:

```powershell
python -m unittest discover -s 'D:\0-AI 项目\本地Qwen推理服务\tests' -v
```

Expected: `FileNotFoundError` 指向 `config/service.json` 或 `PROJECT_INFO.md`。

- [ ] **Step 4: 分配端口、登记项目并生成配置**

```powershell
$registryPath = 'C:\Users\Administrator\.codex\PORT_REGISTRY.json'
$projectRoot = 'D:\0-AI 项目\本地Qwen推理服务'
$registry = Get-Content -Raw -Encoding UTF8 $registryPath | ConvertFrom-Json
$registered = @($registry.projects | ForEach-Object { $_.aiPort } | Where-Object { $_ -ne $null })
$listening = @(
  Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty LocalPort -Unique
)
$assignedPort = 7001..7199 | Where-Object { $_ -notin $registered -and $_ -notin $listening } | Select-Object -First 1
if ($null -eq $assignedPort) { throw 'AI 服务端口 7001-7199 已全部占用' }
$existing = @($registry.projects | Where-Object { $_.techId -eq 'local-qwen-service' })
if ($existing.Count -gt 1) { throw 'PORT_REGISTRY.json 中存在重复的 local-qwen-service' }
if ($existing.Count -eq 1) {
  $assignedPort = [int]$existing[0].aiPort
} else {
  $entry = [pscustomobject]@{
    projectName = '本地Qwen推理服务'
    projectPath = $projectRoot
    techId = 'local-qwen-service'
    frontendPort = $null
    backendPort = $null
    aiPort = [int]$assignedPort
    createdAt = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
  }
  $registry.projects = @($registry.projects) + $entry
  $registry | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 $registryPath
}
$service = [ordered]@{
  host = '127.0.0.1'
  port = [int]$assignedPort
  baseUrl = "http://127.0.0.1:$assignedPort/v1"
  model = 'qwen3.5:9b'
  contextLength = 65536
  parallel = 1
  kvCacheType = 'q8_0'
}
$service | ConvertTo-Json | Set-Content -Encoding UTF8 "$projectRoot\config\service.json"
```

Then create `PROJECT_INFO.md` with the assigned port read from `service.json`; its local URL must equal the `baseUrl` field exactly. Create `README.md` with the scope statement: Qwen is the Hermes reasoning model; AutoDL MiniMax H3 remains the video generator.

- [ ] **Step 5: 验证项目契约通过**

Run:

```powershell
python -m unittest discover -s 'D:\0-AI 项目\本地Qwen推理服务\tests' -v
```

Expected: `Ran 2 tests` and `OK`。

- [ ] **Step 6: 提交项目骨架**

```powershell
git -C 'D:\0-AI 项目\本地Qwen推理服务' add config/service.json tests/test_project_contract.py PROJECT_INFO.md README.md
git -C 'D:\0-AI 项目\本地Qwen推理服务' commit -m "chore: scaffold local Qwen service"
```

---

### Task 2: 安装 Ollama 并实现可重复的服务生命周期脚本

**Files:**
- Create: `D:\0-AI 项目\本地Qwen推理服务\tests\test_service_scripts.py`
- Create: `D:\0-AI 项目\本地Qwen推理服务\scripts\Start-Qwen.ps1`
- Create: `D:\0-AI 项目\本地Qwen推理服务\scripts\Stop-Qwen.ps1`
- Create: `D:\0-AI 项目\本地Qwen推理服务\scripts\Get-QwenStatus.ps1`
- Create: `D:\0-AI 项目\本地Qwen推理服务\.gitignore`

**Interfaces:**
- Consumes: `config/service.json`。
- Produces: 后台 `ollama serve` 进程、`run/ollama.pid`、`logs/ollama.stdout.log`、`logs/ollama.stderr.log`。

- [ ] **Step 1: 写入服务脚本契约测试**

```python
# tests/test_service_scripts.py
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class ServiceScriptsTest(unittest.TestCase):
    def test_start_script_has_required_isolation_and_context(self):
        text = (ROOT / "scripts" / "Start-Qwen.ps1").read_text(encoding="utf-8-sig")
        for required in (
            "OLLAMA_HOST", "OLLAMA_CONTEXT_LENGTH", "OLLAMA_FLASH_ATTENTION",
            "OLLAMA_KV_CACHE_TYPE", "OLLAMA_NUM_PARALLEL", "-WindowStyle Hidden",
        ):
            self.assertIn(required, text)

    def test_stop_script_only_targets_recorded_pid(self):
        text = (ROOT / "scripts" / "Stop-Qwen.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("ollama.pid", text)
        self.assertIn("Stop-Process -Id", text)
        self.assertNotIn("Stop-Process -Name", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试并确认脚本缺失**

```powershell
python -m unittest 'D:\0-AI 项目\本地Qwen推理服务\tests\test_service_scripts.py' -v
```

Expected: `FileNotFoundError` for `Start-Qwen.ps1`。

- [ ] **Step 3: 安装官方 Ollama**

```powershell
winget install --exact --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
$ollamaExe = (Get-Command ollama -ErrorAction Stop).Source
ollama --version
```

Expected: `ollama version` 后跟已安装版本；若 PATH 尚未刷新，使用 `%LOCALAPPDATA%\Programs\Ollama\ollama.exe` 并在新终端复核。

- [ ] **Step 4: 实现启动、停止和状态脚本**

```powershell
# scripts/Start-Qwen.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$cfg = Get-Content -Raw -Encoding UTF8 "$root\config\service.json" | ConvertFrom-Json
$pidFile = "$root\run\ollama.pid"
if (Test-Path -LiteralPath $pidFile) {
  $oldPid = [int](Get-Content -Raw $pidFile)
  if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) { throw "Qwen 服务已运行，PID=$oldPid" }
  Remove-Item -LiteralPath $pidFile -Force
}
$env:OLLAMA_HOST = "$($cfg.host):$($cfg.port)"
$env:OLLAMA_CONTEXT_LENGTH = [string]$cfg.contextLength
$env:OLLAMA_FLASH_ATTENTION = '1'
$env:OLLAMA_KV_CACHE_TYPE = [string]$cfg.kvCacheType
$env:OLLAMA_NUM_PARALLEL = [string]$cfg.parallel
$process = Start-Process -FilePath (Get-Command ollama -ErrorAction Stop).Source `
  -ArgumentList 'serve' -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput "$root\logs\ollama.stdout.log" `
  -RedirectStandardError "$root\logs\ollama.stderr.log"
Set-Content -Encoding ASCII -Path $pidFile -Value $process.Id
Write-Output "Qwen 服务已启动：PID=$($process.Id)，URL=$($cfg.baseUrl)"
```

```powershell
# scripts/Stop-Qwen.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$pidFile = "$root\run\ollama.pid"
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output 'Qwen 服务未运行'; exit 0 }
$servicePid = [int](Get-Content -Raw $pidFile)
$process = Get-Process -Id $servicePid -ErrorAction SilentlyContinue
if ($process) { Stop-Process -Id $servicePid; Wait-Process -Id $servicePid -ErrorAction SilentlyContinue }
Remove-Item -LiteralPath $pidFile -Force
Write-Output 'Qwen 服务已停止'
```

```powershell
# scripts/Get-QwenStatus.ps1
$root = Split-Path -Parent $PSScriptRoot
$cfg = Get-Content -Raw -Encoding UTF8 "$root\config\service.json" | ConvertFrom-Json
$pidFile = "$root\run\ollama.pid"
$running = $false
if (Test-Path -LiteralPath $pidFile) {
  $servicePid = [int](Get-Content -Raw $pidFile)
  $running = $null -ne (Get-Process -Id $servicePid -ErrorAction SilentlyContinue)
}
[pscustomobject]@{ Running=$running; BaseUrl=$cfg.baseUrl; Model=$cfg.model; ContextLength=$cfg.contextLength }
```

`.gitignore` contents:

```gitignore
logs/*.log
run/*.pid
__pycache__/
```

- [ ] **Step 5: 运行静态契约测试**

```powershell
python -m unittest 'D:\0-AI 项目\本地Qwen推理服务\tests\test_service_scripts.py' -v
```

Expected: `Ran 2 tests` and `OK`。

- [ ] **Step 6: 启动服务并拉取模型**

```powershell
& 'D:\0-AI 项目\本地Qwen推理服务\scripts\Start-Qwen.ps1'
$cfg = Get-Content -Raw 'D:\0-AI 项目\本地Qwen推理服务\config\service.json' | ConvertFrom-Json
$env:OLLAMA_HOST = "$($cfg.host):$($cfg.port)"
ollama pull $cfg.model
ollama list
```

Expected: `qwen3.5:9b` appears in `ollama list`。模型下载可能持续较长时间，但不得改用第三方标签规避下载。

- [ ] **Step 7: 提交服务生命周期脚本**

```powershell
git -C 'D:\0-AI 项目\本地Qwen推理服务' add .gitignore scripts tests/test_service_scripts.py
git -C 'D:\0-AI 项目\本地Qwen推理服务' commit -m "feat: manage local Ollama service"
```

---

### Task 3: 添加 OpenAI 接口、工具调用和视觉能力验证器

**Files:**
- Create: `D:\0-AI 项目\本地Qwen推理服务\tests\test_verify_service.py`
- Create: `D:\0-AI 项目\本地Qwen推理服务\scripts\verify_service.py`
- Create: `D:\0-AI 项目\本地Qwen推理服务\tests\fixtures\pixel.png`

**Interfaces:**
- Consumes: `config/service.json` 和 OpenAI 兼容接口。
- Produces: 退出码 `0` 表示 models/chat/tool/vision 全部通过；退出码 `1` 表示至少一项失败；标准输出为不含提示内容与密钥的 JSON 摘要。

- [ ] **Step 1: 写入使用本地假服务器的失败测试**

```python
# tests/test_verify_service.py
import json
import pathlib
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from scripts.verify_service import verify


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        return

    def do_GET(self):
        body = {"data": [{"id": "qwen3.5:9b"}]}
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if request.get("tools"):
            message = {"tool_calls": [{"function": {"name": "echo", "arguments": "{\"text\":\"ok\"}"}}]}
        else:
            message = {"content": "OK"}
        body = {"choices": [{"message": message}]}
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(body).encode())


class VerifyServiceTest(unittest.TestCase):
    def test_verify_accepts_openai_models_chat_and_tool_calls(self):
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            result = verify(f"http://127.0.0.1:{server.server_port}/v1", "qwen3.5:9b", check_vision=False)
            self.assertEqual(result, {"models": True, "chat": True, "tools": True, "vision": None})
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 确认验证器尚未实现**

```powershell
python -m unittest 'D:\0-AI 项目\本地Qwen推理服务\tests\test_verify_service.py' -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.verify_service'`。

- [ ] **Step 3: 实现最小验证器**

```python
# scripts/verify_service.py
import argparse
import base64
import json
import pathlib
import urllib.request


def request_json(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def verify(base_url, model, check_vision=True):
    models = request_json(f"{base_url}/models")
    found = any(item.get("id") == model for item in models.get("data", []))
    chat = request_json(f"{base_url}/chat/completions", {
        "model": model, "messages": [{"role": "user", "content": "只回复 OK"}], "stream": False,
    })
    chat_ok = bool(chat.get("choices", [{}])[0].get("message", {}).get("content"))
    tools = request_json(f"{base_url}/chat/completions", {
        "model": model,
        "messages": [{"role": "user", "content": "调用 echo 工具，参数 text 必须为 ok"}],
        "tools": [{"type": "function", "function": {"name": "echo", "description": "回显文本", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}],
        "tool_choice": "auto", "stream": False,
    })
    tool_ok = bool(tools.get("choices", [{}])[0].get("message", {}).get("tool_calls"))
    vision_ok = None
    if check_vision:
        pixel = base64.b64encode((pathlib.Path(__file__).parents[1] / "tests" / "fixtures" / "pixel.png").read_bytes()).decode()
        vision = request_json(f"{base_url}/chat/completions", {
            "model": model,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "只回复 IMAGE_OK"}, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{pixel}"}}]}],
            "stream": False,
        })
        vision_ok = bool(vision.get("choices", [{}])[0].get("message", {}).get("content"))
    return {"models": found, "chat": chat_ok, "tools": tool_ok, "vision": vision_ok}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--skip-vision", action="store_true")
    args = parser.parse_args()
    cfg = json.loads(pathlib.Path(args.config).read_text(encoding="utf-8-sig"))
    result = verify(cfg["baseUrl"], cfg["model"], not args.skip_vision)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if all(value is True or value is None for value in result.values()) else 1)
```

Create `tests/fixtures/pixel.png` as a valid local 1×1 PNG fixture; generate it once from the fixed base64 string `iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=` and commit the binary fixture.

- [ ] **Step 4: 运行单元测试**

```powershell
Set-Location 'D:\0-AI 项目\本地Qwen推理服务'
python -m unittest tests.test_verify_service -v
```

Expected: `Ran 1 test` and `OK`。

- [ ] **Step 5: 对真实 Qwen 服务运行验证**

```powershell
python 'D:\0-AI 项目\本地Qwen推理服务\scripts\verify_service.py' --config 'D:\0-AI 项目\本地Qwen推理服务\config\service.json'
$cfg = Get-Content -Raw 'D:\0-AI 项目\本地Qwen推理服务\config\service.json' | ConvertFrom-Json
$env:OLLAMA_HOST = "$($cfg.host):$($cfg.port)"
ollama ps
nvidia-smi --query-compute-apps=process_name,used_memory --format=csv
```

Expected: JSON is `{"models": true, "chat": true, "tools": true, "vision": true}`；`ollama ps` 的 `CONTEXT` 为至少 `65536`。若上下文不足或显存不足，停止此任务并按设计文档记录诊断，不把 Hermes 配置为虚假的 64K。

- [ ] **Step 6: 提交验证器**

```powershell
git -C 'D:\0-AI 项目\本地Qwen推理服务' add scripts/verify_service.py tests/test_verify_service.py tests/fixtures/pixel.png
git -C 'D:\0-AI 项目\本地Qwen推理服务' commit -m "test: verify Qwen OpenAI compatibility"
```

---

### Task 4: 以命名提供商接入 Hermes 并保留 DeepSeek

**Files:**
- Create: `D:\0-AI 项目\本地Qwen推理服务\tests\test_hermes_contract.py`
- Create: `D:\0-AI 项目\本地Qwen推理服务\scripts\Test-HermesConfig.ps1`
- Modify: Hermes 当前配置文件，由 `hermes config path` 返回；预期位于活动 `HERMES_HOME` 下的 `config.yaml`
- Create: Hermes 配置文件同目录下由 `Get-Date -Format 'yyyyMMdd-HHmmss'` 生成的时间戳备份

**Interfaces:**
- Consumes: Hermes CLI、当前 DeepSeek 模型配置、`config/service.json`。
- Produces: `providers.local-qwen` 命名端点；切换命令固定为 `/model custom:local-qwen:qwen3.5:9b`。

- [ ] **Step 1: 写入 Hermes 配置审计测试**

```python
# tests/test_hermes_contract.py
import json
import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class HermesContractTest(unittest.TestCase):
    def test_named_provider_matches_service(self):
        service = json.loads((ROOT / "config" / "service.json").read_text(encoding="utf-8-sig"))
        def get(key):
            return subprocess.check_output(["hermes", "config", "get", key, "--json"], text=True, encoding="utf-8").strip()
        self.assertEqual(json.loads(get("providers.local-qwen.api")), service["baseUrl"])
        self.assertEqual(json.loads(get("providers.local-qwen.transport")), "chat_completions")
        self.assertEqual(json.loads(get("providers.local-qwen.default_model")), service["model"])
        key = r"providers.local-qwen.models.qwen3\.5:9b.context_length"
        self.assertEqual(json.loads(get(key)), 65536)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 保存当前模型身份并确认测试失败**

```powershell
$projectRoot = 'D:\0-AI 项目\本地Qwen推理服务'
hermes config get model --json | Set-Content -Encoding UTF8 "$projectRoot\run\hermes-model-before.json"
python -m unittest "$projectRoot\tests\test_hermes_contract.py" -v
```

Expected: `providers.local-qwen` 不存在，测试失败；`hermes-model-before.json` 只记录模型配置，不读取或输出 `.env`。

- [ ] **Step 3: 备份配置并写入命名提供商**

```powershell
$projectRoot = 'D:\0-AI 项目\本地Qwen推理服务'
$cfg = Get-Content -Raw "$projectRoot\config\service.json" | ConvertFrom-Json
$hermesConfig = (hermes config path).Trim()
if (-not (Test-Path -LiteralPath $hermesConfig)) { throw "Hermes config 不存在：$hermesConfig" }
$backup = Join-Path (Split-Path -Parent $hermesConfig) ("config.before-local-qwen.{0}.yaml" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
Copy-Item -LiteralPath $hermesConfig -Destination $backup
hermes config set providers.local-qwen.api $cfg.baseUrl --force
hermes config set providers.local-qwen.transport chat_completions --force
hermes config set providers.local-qwen.default_model $cfg.model --force
hermes config set 'providers.local-qwen.models.qwen3\.5:9b.context_length' 65536 --force
hermes config set 'providers.local-qwen.models.qwen3\.5:9b.supports_vision' true --force
hermes config check
```

Expected: `hermes config check` 无 unknown provider、缺失 Base URL 或无效 YAML 错误。不要读取、复制或打印 Hermes `.env`。

- [ ] **Step 4: 实现不泄密的配置审计脚本**

```powershell
# scripts/Test-HermesConfig.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$cfg = Get-Content -Raw "$root\config\service.json" | ConvertFrom-Json
$api = hermes config get providers.local-qwen.api --json | ConvertFrom-Json
$transport = hermes config get providers.local-qwen.transport --json | ConvertFrom-Json
$model = hermes config get providers.local-qwen.default_model --json | ConvertFrom-Json
$context = hermes config get 'providers.local-qwen.models.qwen3\.5:9b.context_length' --json | ConvertFrom-Json
if ($api -ne $cfg.baseUrl) { throw 'Hermes Base URL 与服务配置不一致' }
if ($transport -ne 'chat_completions') { throw 'Hermes transport 必须为 chat_completions' }
if ($model -ne $cfg.model) { throw 'Hermes 模型名与服务配置不一致' }
if ([int]$context -ne 65536) { throw 'Hermes 上下文必须为 65536' }
Write-Output "Hermes local-qwen 配置有效：$model @ $api，context=$context"
```

- [ ] **Step 5: 运行配置测试并确认 DeepSeek 仍可见**

```powershell
Set-Location 'D:\0-AI 项目\本地Qwen推理服务'
python -m unittest tests.test_hermes_contract -v
& '.\scripts\Test-HermesConfig.ps1'
hermes config get model --json
```

Expected: Python test passes；审计脚本成功；当前 `model` 输出仍包含实施前保存的 DeepSeek provider/model，或能通过 Hermes 已配置模型列表切回该组合。不得输出任何 API Key。

- [ ] **Step 6: 直接调用命名提供商验证 Hermes 主循环**

```powershell
hermes chat --provider custom:local-qwen --model qwen3.5:9b -t file -q "不要修改文件。先读取当前目录名称，再用一句中文报告；必须通过文件工具获取信息。"
```

Expected: Hermes 显示 provider `custom:local-qwen`、context `65536`，并产生真实工具调用；若只打印工具 JSON，则此任务失败，不进入技能回归。

- [ ] **Step 7: 提交 Hermes 集成审计代码**

```powershell
git -C 'D:\0-AI 项目\本地Qwen推理服务' add scripts/Test-HermesConfig.ps1 tests/test_hermes_contract.py
git -C 'D:\0-AI 项目\本地Qwen推理服务' commit -m "feat: integrate Qwen with Hermes"
```

---

### Task 5: 执行 ayh-h3 非付费回归并形成对照报告

**Files:**
- Create: `D:\0-AI 项目\本地Qwen推理服务\tests\prompts\ayh_h3_regression.txt`
- Create: `D:\0-AI 项目\本地Qwen推理服务\scripts\run_ayh_regression.ps1`
- Create: `D:\0-AI 项目\本地Qwen推理服务\reports\ayh-h3-qwen-evaluation.md`

**Interfaces:**
- Consumes: Hermes `custom:local-qwen`、`D:\0-AI 项目\ayh-h3\skill-package\product-video-pipeline`。
- Produces: 不含密钥和付费任务 ID 的回归记录，字段包括规则遵循、字段完整性、工具调用、耗时、是否触网、是否产生付费提交。

- [ ] **Step 1: 写入固定回归提示词**

```text
这是模型接入回归，不是新的产品视频任务。你只可使用 file 工具做只读技能规则分析：不要写入或修改任何文件，不要调用 terminal、web、network 或 AutoDL，不要读取或显示任何 API Key，不要创建批次，不要扫描产品目录，不要生成图片或视频，也不要运行命令或脚本。请读取 product-video-pipeline 技能说明，然后回答：只有用户明确说出哪些触发词时才能启动？正式付费提交之前需要哪些授权？请明确区分新批次与 V02 独立重跑的授权边界。仅报告规则分析；宿主会在隔离环境中单独运行 self_test.py。
```

- [ ] **Step 2: 实现阻止付费提交的回归脚本**

```powershell
# scripts/run_ayh_regression.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$skillRoot = 'D:\0-AI 项目\ayh-h3\skill-package\product-video-pipeline'
$runRoot = Join-Path $root 'run'
$globalSkillRoot = 'C:\Users\Administrator\.agents\skills\product-video-pipeline'
$prompt = Get-Content -Raw "$root\tests\prompts\ayh_h3_regression.txt"
$before = Get-Date
$null = New-Item -ItemType Directory -Force -Path $runRoot
& "$root\scripts\Test-HermesConfig.ps1"
# 仅接受 custom:local-qwen 到 http://127.0.0.1:7001/v1；调用前后对两个技能树逐文件 SHA256 快照。
# 捕获输出先脱敏，随后 fail closed 拒绝 write_file、patch、terminal、web/network、AutoDL task_id、非 dry-run submit 或技能树差异。
$output = hermes chat --provider custom:local-qwen --model qwen3.5:9b -t file -q $prompt 2>&1
$exitCode = $LASTEXITCODE
$output | ConvertTo-SafeText | Set-Content -Encoding UTF8 "$runRoot\ayh-h3-qwen-output.txt"
if ($exitCode -ne 0) { throw "Hermes Qwen 回归失败，退出码=$exitCode" }
# 读取 self_test.py，任一 autodl_h3.py submit 路径若未含 --dry-run 则拒绝运行。
# 宿主执行时清空 AUTODL_API_KEY，HTTP_PROXY/HTTPS_PROXY/ALL_PROXY 指向 http://127.0.0.1:9，NO_PROXY 仅为 127.0.0.1,localhost。
Push-Location $skillRoot
try { python scripts/self_test.py; if ($LASTEXITCODE -ne 0) { throw '技能 self_test.py 失败' } }
finally { Pop-Location }
$elapsed = [math]::Round(((Get-Date) - $before).TotalSeconds, 1)
Write-Output "Qwen 只读回归与宿主自测完成，耗时 ${elapsed}s；未执行非 dry-run 的正式付费提交"
```

- [ ] **Step 3: 运行技能包基线自测**

```powershell
Set-Location 'D:\0-AI 项目\ayh-h3\skill-package\product-video-pipeline'
python scripts/self_test.py
```

Expected: 宿主在隔离环境中运行并通过；脚本先静态确认其内部每个 AutoDL `submit` 都带 `--dry-run`，且不联网、不扣费。Qwen 不执行此步骤。

- [ ] **Step 4: 运行 Qwen 回归**

```powershell
& 'D:\0-AI 项目\本地Qwen推理服务\scripts\run_ayh_regression.ps1'
```

Expected: Hermes 仅以 file 工具正确列出技能的明确触发约束与付费授权约束，不运行命令或脚本；模型输出中不得有越界工具轨迹、AutoDL task ID、API Key 或 non-dry-run submit 迹象。宿主自测成功须单独记录，不得归因为 Qwen。

- [ ] **Step 5: 形成评估报告并判定是否晋升**

在 `reports/ayh-h3-qwen-evaluation.md` 写入以下固定表头，并根据真实结果填写 `通过` 或 `失败`：

```markdown
# ayh-h3 Qwen 接入评估

| 检查项 | 结果 | 证据摘要 |
|---|---|---|
| 64K 实际上下文 |  |  |
| OpenAI Chat Completions |  |  |
| 原生工具调用 |  |  |
| 图片输入 |  |  |
| 技能触发词识别 |  |  |
| 付费授权边界 |  |  |
| product-video-pipeline self_test |  |  |
| AutoDL 正式提交次数 |  | 必须为 0 |

结论只能是：继续测试，或可设为默认。任何关键项失败时必须选择“继续测试”。
```

评估必须区分模型工具能力与宿主自测：Task 3 已提交的 64K、OpenAI Chat Completions、原生工具和双图 vision 证据可引用；Task 5 只验证 Qwen 的只读技能规则分析、安全工具边界和隔离宿主自测。若模型遗漏新批次授权不继承或 V02 独立重跑须重新授权，则“付费授权边界”为失败并保持“继续测试”。正式提交字段写“未执行非 dry-run 的正式付费提交”；技能自测字段写“宿主通过，非 Qwen 执行”。

- [ ] **Step 6: 提交回归资产和报告**

```powershell
git -C 'D:\0-AI 项目\本地Qwen推理服务' add tests/prompts/ayh_h3_regression.txt scripts/run_ayh_regression.ps1 reports/ayh-h3-qwen-evaluation.md
git -C 'D:\0-AI 项目\本地Qwen推理服务' commit -m "test: evaluate Qwen on ayh-h3 workflow"
```

---

### Task 6: 完成运行手册、回退验证和服务器迁移接口

**Files:**
- Modify: `D:\0-AI 项目\本地Qwen推理服务\README.md`
- Create: `D:\0-AI 项目\本地Qwen推理服务\docs\运行手册.md`
- Create: `D:\0-AI 项目\本地Qwen推理服务\docs\服务器迁移.md`

**Interfaces:**
- Consumes: 已验证的启动/停止/检查命令与 Hermes 命名提供商。
- Produces: 日常运行、故障回退及把 Base URL 切到服务器 HTTPS 地址的可复现说明。

- [ ] **Step 1: 写入文档契约测试**

Add to `tests/test_project_contract.py`:

```python
    def test_operations_docs_cover_required_commands(self):
        runbook = (ROOT / "docs" / "运行手册.md").read_text(encoding="utf-8")
        migration = (ROOT / "docs" / "服务器迁移.md").read_text(encoding="utf-8")
        for required in ("Start-Qwen.ps1", "Stop-Qwen.ps1", "verify_service.py", "custom:local-qwen", "DeepSeek"):
            self.assertIn(required, runbook)
        for required in ("HTTPS", "API Key", "vLLM", "--enable-auto-tool-choice", "--tool-call-parser hermes"):
            self.assertIn(required, migration)
```

- [ ] **Step 2: 确认文档测试失败**

```powershell
Set-Location 'D:\0-AI 项目\本地Qwen推理服务'
python -m unittest tests.test_project_contract.ProjectContractTest.test_operations_docs_cover_required_commands -v
```

Expected: `FileNotFoundError` for `docs/运行手册.md`。

- [ ] **Step 3: 编写运行手册**

`docs/运行手册.md` 必须逐条包含：启动服务、状态检查、接口验证、Hermes 临时选择 `/model custom:local-qwen:qwen3.5:9b`、切回实施前记录的 DeepSeek provider/model、停止服务、查看不含密钥的日志，以及显存不足时不伪造 64K 的处理顺序。

`README.md` 必须列出固定架构、项目端口、本地 URL、模型、上下文、单并发、快速检查命令，以及“AutoDL MiniMax H3 仍是视频生成器”的边界说明。

- [ ] **Step 4: 编写服务器迁移说明**

`docs/服务器迁移.md` 必须包含：服务器 GPU 选型后加载更大 Qwen、vLLM 启动时使用 `--max-model-len 65536 --enable-auto-tool-choice --tool-call-parser hermes`、仅通过 HTTPS 暴露、启用 API Key 和防火墙、在 Hermes 新增 `custom:server-qwen` 而不是覆盖本机端点、复用 Task 3 与 Task 5 验证、通过后再切默认模型。

- [ ] **Step 5: 运行完整验证**

```powershell
Set-Location 'D:\0-AI 项目\本地Qwen推理服务'
python -m unittest discover -s tests -v
& '.\scripts\Get-QwenStatus.ps1'
& '.\scripts\Test-HermesConfig.ps1'
python '.\scripts\verify_service.py' --config '.\config\service.json'
git status --short
```

Expected: 所有单元测试 `OK`；Qwen 服务 Running 为 `True`；Hermes 审计成功；接口四项均为 `true`；Git 仅显示本任务文档和测试修改。

- [ ] **Step 6: 提交文档并记录最终版本**

```powershell
git -C 'D:\0-AI 项目\本地Qwen推理服务' add README.md docs tests/test_project_contract.py
git -C 'D:\0-AI 项目\本地Qwen推理服务' commit -m "docs: add Qwen operations and migration guides"
git -C 'D:\0-AI 项目\本地Qwen推理服务' log --oneline -6
```

Expected: 六个以内的聚焦提交，工作树无计划内未提交文件；现有 `ayh-h3` 仓库的用户改动保持原样。

## Final Acceptance

- [ ] `PORT_REGISTRY.json` 只有一个 `local-qwen-service` 项目条目，端口在 `7001-7199` 且未冲突。
- [ ] `PROJECT_INFO.md` 和固定端口配置齐全。
- [ ] Ollama 只绑定 `127.0.0.1`，Qwen 模型为官方 `qwen3.5:9b`。
- [ ] `ollama ps` 显示实际上下文至少 65536，服务单并发。
- [ ] OpenAI models/chat/tool/vision 验证全部通过。
- [ ] Hermes 的 `custom:local-qwen` 可运行真实工具调用，DeepSeek 可恢复。
- [ ] `ayh-h3` 自测与 Qwen 非付费回归通过，AutoDL 正式提交次数为 0。
- [ ] 没有密钥进入日志、Git 或最终回复。
- [ ] 运行手册和服务器迁移说明能够从空终端复现。
