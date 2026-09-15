"""Offline human listening receipts. No ASR, generation, or automatic pass."""
import argparse
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path):
    try:
        row = json.loads(Path(path).read_text(encoding='utf-8'))
        return row if isinstance(row, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def prepare_review(report, video, segments):
    sha = _hash(video)
    plan_hash = hashlib.sha256(json.dumps(segments, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    old = _read(report)
    if old.get('sha256') == sha and old.get('plan_sha256') == plan_hash:
        return old
    spec = importlib.util.spec_from_file_location('audio_prompt_contract', Path(__file__).with_name('generation_prompt_contract.py'))
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    data = {'sha256': sha, 'plan_sha256': plan_hash, 'status': 'pending_listening',
            'video_path': str(Path(video).resolve()), 'expected_dialogue': segments,
            'checks': ['完整试听全片', '逐句台词与说话人一致', '交接停顿及首尾无额外人声或伪语音'],
            'notice': '解码通过不代表口播合格；转写不能替代试听；没有自动语义检测。'}
    try:
        data['timing'] = contract.audio_schedule(segments)
    except (ValueError, TypeError, KeyError):
        data['timing'] = []
        data['notice'] += '缺少有效台词时间表，请对照原始台词完整试听。'
    if old:
        data['previous_review'] = old
    _write(report, data)
    return data


def review_status(report, video):
    row = _read(report)
    status = row.get('status')
    if (row.get('sha256') != _hash(video) or status not in {'passed', 'failed'}
            or row.get('listened_full') is not True
            or not isinstance(row.get('reviewer'), str) or not row['reviewer'].strip()
            or not isinstance(row.get('notes'), str) or not row['notes'].strip()):
        status = 'pending_listening'
    return {'status': status, 'report_path': str(Path(report).resolve()),
            'notice': '音频需完整试听确认；技术检查不代表口播合格。'}


def record_review(report, video, verdict, reviewer, notes, listened_full):
    row = _read(report)
    if row.get('sha256') != _hash(video):
        raise ValueError('视频哈希与试听清单不一致，请先重新准备清单')
    if not listened_full or not reviewer.strip() or not notes.strip():
        raise ValueError('必须完整试听并填写试听人及结论，不能依据转写自动判通过')
    if verdict not in {'passed', 'failed'}:
        raise ValueError('结论必须为passed或failed')
    row.setdefault('history', []).append({k: row.get(k) for k in ('status', 'reviewer', 'notes', 'reviewed_at')})
    row.update(status=verdict, reviewer=reviewer, notes=notes, listened_full=True,
               reviewed_at=datetime.now(timezone.utc).isoformat())
    _write(report, row)
    return review_status(report, video)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--verdict', choices=['passed', 'failed'], required=True)
    parser.add_argument('--reviewer', required=True)
    parser.add_argument('--notes', required=True)
    parser.add_argument('--listened-full', action='store_true')
    args = parser.parse_args()
    print(json.dumps(record_review(args.report, args.video, args.verdict, args.reviewer, args.notes, args.listened_full), ensure_ascii=False))


if __name__ == '__main__':
    main()
