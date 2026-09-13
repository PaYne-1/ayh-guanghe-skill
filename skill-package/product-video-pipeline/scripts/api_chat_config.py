#!/usr/bin/env python3
"""Configure user-authorized chat credentials without an interactive terminal.

Accept JSON on stdin, or call save_chat_configuration(payload) from a host tool.
Never print payloads or raw exceptions. No network requests are made.
"""
import json
import sys

from api_config import (
    CONFIG_SCHEMAS, ConfigurationInputError, PersistenceRollbackError,
    WindowsUserEnvironmentStore, format_error, status_payload,
    validate_category_values,
)


def _string(value):
    if value is None:
        return ''
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ConfigurationInputError('配置字段必须是文本或数字')
    return str(value).strip()


def save_chat_configuration(payload, store=None):
    """Validate all requested categories, persist together, verify and mask."""
    if not isinstance(payload, dict):
        raise ConfigurationInputError('配置必须是 JSON 对象')
    store = store or WindowsUserEnvironmentStore()
    connection = payload.get('connection', {})
    if not isinstance(connection, dict):
        raise ConfigurationInputError('connection 必须是 JSON 对象')
    categories = [name for name in CONFIG_SCHEMAS if name in payload]
    if not categories:
        raise ConfigurationInputError('请提供 autodl、image 或 text 配置对象')
    changes = {}
    for category in categories:
        data = payload[category]
        if not isinstance(data, dict):
            raise ConfigurationInputError('每个 API 类别必须是 JSON 对象')
        if category == 'autodl':
            # Third-party connection keys never implicitly overwrite AutoDL.
            values = {
                'AUTODL_API_KEY': _string(data.get('key')) or store.get('AUTODL_API_KEY') or '',
                'AUTODL_AUTH_SCHEME': _string(data.get('auth_scheme')) or store.get('AUTODL_AUTH_SCHEME') or 'bearer',
            }
        else:
            prefix = 'PRODUCT_VIDEO_' + category.upper() + '_API'
            fields = {
                'PROVIDER': data.get('provider', payload.get('provider')),
                'BASE_URL': data.get('base_url', connection.get('url', payload.get('base_url'))),
                'MODEL': data.get('model'),
                'KEY': data.get('key', connection.get('key', payload.get('key'))),
            }
            if category == 'image':
                fields['UNIT_PRICE_YUAN'] = data.get('unit_price_yuan')
            values = {prefix + '_' + field: _string(value) or store.get(prefix + '_' + field) or '' for field, value in fields.items()}
            url_name = prefix + '_BASE_URL'
            if values[url_name] and '://' not in values[url_name]:
                values[url_name] = 'https://' + values[url_name]
        validate_category_values(category, values)
        changes.update(values)
    previous = {name: store.get(name) for name in changes}
    try:
        store.set_many(changes)
        if any(store.get(name) != value for name, value in changes.items()):
            raise RuntimeError('永久配置回读不一致')
        status = status_payload(store)
    except Exception:
        try:
            store.set_many(previous)
        except Exception as rollback_error:
            raise PersistenceRollbackError('配置写入和回滚失败') from rollback_error
        raise
    return {
        'result': '配置已永久保存到 Windows 当前用户环境变量，并完成回读验证',
        'validation': '已完成本地格式检查；未执行联网或计费验证',
        'categories': {name: status[name] for name in categories},
    }


def main():
    try:
        payload = json.load(sys.stdin)
        result = save_chat_configuration(payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({'error': format_error(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
