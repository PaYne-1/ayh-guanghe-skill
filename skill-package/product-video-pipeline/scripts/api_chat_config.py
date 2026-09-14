#!/usr/bin/env python3
"""Configure user-authorized chat credentials without an interactive terminal.

Accept JSON on stdin, or call save_chat_configuration(payload) from a host tool.
Never print payloads or raw exceptions. No network requests are made.
"""
import json
import re
import html
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


def parse_chat_text(text):
    """Parse explicit labeled values only; never infer one category's key from another."""
    text = html.unescape(text).replace('\\_', '_').replace('\\\r\n', '\n').replace('\\\n', '\n')
    payload = {}
    def assign(target, field, value):
        if field in target and target[field] != value:
            raise ConfigurationInputError('同一配置字段出现不同值，请明确要使用哪一个')
        target[field] = value
    for line in text.splitlines():
        line = line.strip().strip('\\').strip()
        match = re.match(r'^([^:：]+)[:：]\s*(.*)$', line)
        if not match:
            continue
        label = re.sub(r'\s+', '', match.group(1)).upper()
        value = match.group(2).strip().strip('\\').strip().strip('`')
        if label == '连接信息':
            try:
                connection = json.loads(value)
            except ValueError:
                raise ConfigurationInputError('连接信息 JSON 格式无效') from None
            if not isinstance(connection, dict):
                raise ConfigurationInputError('连接信息必须是 JSON 对象')
            for field, item in connection.items():
                assign(payload.setdefault('connection', {}), field, item)
            continue
        if label in ('第三方API', '第三方APIKEY', '第三方API密钥'):
            assign(payload.setdefault('connection', {}), 'key', value)
            continue
        if label in ('第三方API地址', '第三方地址'):
            assign(payload.setdefault('connection', {}), 'url', value)
            continue
        if label in ('第三方服务商', '服务商'):
            assign(payload, 'provider', value)
            continue
        if label in ('AUTODL_API_KEY', 'AUTODL_AUTH_SCHEME'):
            field = 'key' if label.endswith('_KEY') else 'auth_scheme'
            category = 'autodl'
        elif label.startswith('第三方生图'):
            category = 'image'
            suffix = label[len('第三方生图'):]
            field = {'API': 'key', '模型': 'model', '模型选择': 'model', 'API模型': 'model', '地址': 'base_url',
                     'API地址': 'base_url', 'BASEURL': 'base_url', '服务商': 'provider',
                     '单价': 'unit_price_yuan', '单张价格': 'unit_price_yuan'}.get(suffix)
        elif label.startswith('第三方文本生成') or label.startswith('第三方文本'):
            category = 'text'
            suffix = label.replace('第三方文本生成', '', 1) if label.startswith('第三方文本生成') else label.replace('第三方文本', '', 1)
            field = {'API': 'key', '模型': 'model', '模型选择': 'model', 'API模型': 'model', '地址': 'base_url',
                     'API地址': 'base_url', 'BASEURL': 'base_url', '服务商': 'provider'}.get(suffix)
        else:
            continue
        if field:
            data = payload.setdefault(category, {})
            if field in data and data[field] != value:
                raise ConfigurationInputError('同一配置字段出现不同值，请明确要使用哪一个')
            data[field] = value
    if not payload:
        raise ConfigurationInputError('未识别到 API 类别标签，请提供明确的类别、密钥或模型字段')
    if 'image' in payload and 'text' in payload:
        payload['shared_third_party'] = True
    return payload


def save_chat_configuration(payload, store=None):
    """Validate all requested categories, persist together, verify and mask."""
    if isinstance(payload, str):
        payload = parse_chat_text(payload)
    if not isinstance(payload, dict):
        raise ConfigurationInputError('配置必须是 JSON 对象')
    store = store or WindowsUserEnvironmentStore()
    if payload.get('shared_third_party'):
        payload = dict(payload)
        image, text = dict(payload.get('image', {})), dict(payload.get('text', {}))
        common = payload.get('connection', {})
        if not isinstance(common, dict):
            raise ConfigurationInputError('connection 必须是 JSON 对象')
        for field, suffix in (('key', 'KEY'), ('base_url', 'BASE_URL'), ('provider', 'PROVIDER')):
            common_value = common.get('url' if field == 'base_url' else field) or payload.get(field)
            explicit = [v for v in (image.get(field), text.get(field), common_value) if v]
            if len(set(explicit)) > 1:
                raise ConfigurationInputError('图片和文本共用 API，但提供了不同的 ' + field + '，请明确共享值')
            saved = [store.get('PRODUCT_VIDEO_' + category + '_API_' + suffix) for category in ('IMAGE', 'TEXT')]
            saved = [v for v in saved if v]
            if not explicit and len(set(saved)) > 1:
                raise ConfigurationInputError('已保存的图片和文本 ' + field + ' 不一致，请提供本次共享值')
            value = explicit[0] if explicit else (saved[0] if saved else '')
            image[field] = text[field] = value
        payload['image'], payload['text'] = image, text
    connection = payload.get('connection', {})
    if not isinstance(connection, dict):
        raise ConfigurationInputError('connection 必须是 JSON 对象')
    categories = [name for name in CONFIG_SCHEMAS if name in payload]
    if not categories:
        raise ConfigurationInputError('请提供 autodl、image 或 text 配置对象')
    changes = {}
    for category in categories:
        clear_price = False
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
            if category == 'image' and not _string(data.get('unit_price_yuan')):
                clear_price = any(values[prefix + '_' + field] != (store.get(prefix + '_' + field) or '')
                                  for field in ('PROVIDER', 'BASE_URL', 'MODEL'))
                if clear_price:
                    values[prefix + '_UNIT_PRICE_YUAN'] = ''
        validate_category_values(category, values, allow_missing_price=True)
        values = {name: value for name, value in values.items() if value or not name.endswith('_UNIT_PRICE_YUAN')}
        changes.update(values)
        if clear_price:
            changes['PRODUCT_VIDEO_IMAGE_API_UNIT_PRICE_YUAN'] = None
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
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.lstrip().startswith(('{', '[')) else raw
        result = save_chat_configuration(payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({'error': format_error(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
