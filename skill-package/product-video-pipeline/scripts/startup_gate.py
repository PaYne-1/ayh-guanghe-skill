"""Deterministic startup display and CLI confirmation validation. No network."""
import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIELDS = ('product_dir', 'product_name', 'selling_points', 'total', 'mode',
          'resolution', 'max_budget', 'cover_reference_dir', 'image_provider')


def render():
    content = (Path(__file__).resolve().parents[1] / 'references/startup-checklist.md').read_text(encoding='utf-8')
    start = content.index('## 你需要提供的内容')
    end = content.index('## 回复后的本地验证与执行')
    return content[start:end].strip()


def validate_record(record):
    if not isinstance(record, dict) or record.get('confirmed') is not True or not isinstance(record.get('user_reply'), str) or not record['user_reply'].strip():
        raise ValueError('缺少本次用户明确确认：请先展示启动清单并等待回复')
    fields = record.get('fields', {})
    if not isinstance(fields, dict) or any(key not in fields or fields[key] in (None, '', []) for key in FIELDS):
        raise ValueError('启动参数不完整：禁止使用默认预算、数量或渠道')
    if type(fields['total']) is not int or fields['total'] <= 0:
        raise ValueError('视频数量必须为正整数')
    for key in ('product_dir', 'product_name', 'cover_reference_dir', 'mode', 'resolution', 'image_provider'):
        if not isinstance(fields[key], str) or not fields[key].strip():
            raise ValueError('启动字段必须为非空文本：' + key)
    if fields['mode'] not in ('auto', 'learning') or fields['resolution'] not in ('768P', '2K') or fields['image_provider'] not in ('codex', 'chatgpt_web', 'third_party_api'):
        raise ValueError('运行模式、分辨率或渠道无效')
    if not isinstance(fields['selling_points'], list) or not all(isinstance(p, str) and p.strip() for p in fields['selling_points']):
        raise ValueError('卖点必须为非空文本列表')
    try:
        budget = Decimal(str(fields['max_budget']))
        if not budget.is_finite() or budget <= 0:
            raise ValueError('总预算必须为正数')
    except InvalidOperation:
        raise ValueError('总预算必须为正数') from None
    return fields


def require_confirmation(path, actual):
    if path is None:
        raise ValueError('STARTUP_CONFIRMATION_REQUIRED：先运行 startup_gate.py prompt，等待用户确认；禁止直接 init')
    record = json.loads(Path(path).read_text(encoding='utf-8'))
    fields = validate_record(record)
    for key in FIELDS:
        expected, supplied = fields[key], actual[key]
        if key in ('product_dir', 'cover_reference_dir'):
            equal = Path(expected).resolve() == Path(supplied).resolve()
        elif key == 'max_budget':
            equal = Decimal(str(expected)) == Decimal(str(supplied))
        elif key == 'selling_points':
            equal = list(expected) == list(supplied)
        else:
            equal = expected == supplied
        if not equal:
            raise ValueError('启动参数与本次确认不一致：' + key)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prompt', 'confirm'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'prompt':
            print(render())
        else:
            record = json.load(sys.stdin)
            validate_record(record)
            if args.output is None:
                raise ValueError('confirm 需要 --output 保存本次确认记录')
            # Exclusive creation avoids overwriting another task's authorization.
            with args.output.open('x', encoding='utf-8') as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
            print('启动确认记录已保存')
        return 0
    except (ValueError, OSError, TypeError):
        print('启动确认失败：检查用户确认、全部字段、输出路径；未初始化产品任务', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
