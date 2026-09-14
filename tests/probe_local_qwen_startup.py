"""Isolated local model probe. Offered tools are simulated; no task commands run."""
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skill-package/product-video-pipeline'
sys.path.insert(0, str(SKILL / 'scripts'))
from startup_gate import render


def ask(messages):
    body = {'model': 'qwen3.5:9b', 'messages': messages, 'stream': False,
            'temperature': 0, 'max_tokens': 6000,
            'tools': [{'type': 'function', 'function': {
                'name': 'terminal', 'description': '运行本机命令',
                'parameters': {'type': 'object', 'properties': {'command': {'type': 'string'}}, 'required': ['command']}}}]}
    request = Request('http://127.0.0.1:7001/v1/chat/completions',
                      data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=180) as response:
        return json.load(response)['choices'][0]['message']


messages = [
    {'role': 'system', 'content': '你是 Hermes 中运行的助手。请遵守以下已加载技能。\n' + (SKILL / 'SKILL.md').read_text(encoding='utf-8')},
    {'role': 'user', 'content': '开始光合视频任务'},
]
first = ask(messages)
calls = first.get('tool_calls', [])
safe = len(calls) == 1 and 'startup_gate.py prompt' in calls[0]['function']['arguments']
print(json.dumps({'requested_fixed_template': safe}, ensure_ascii=False), flush=True)
if not safe:
    raise SystemExit(1)
messages.append(first)
messages.append({'role': 'tool', 'tool_call_id': calls[0]['id'], 'content': render()})
final = ask(messages)
content = final.get('content') or ''
passed = all(x in content for x in ('你需要提供的内容', '本次配置明细', '请你回复')) and not final.get('tool_calls')
print(json.dumps({'returned_three_sections_and_stopped': passed}, ensure_ascii=False), flush=True)
raise SystemExit(0 if passed else 1)
