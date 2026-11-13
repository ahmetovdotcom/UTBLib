"""Shared, bounded schema for public site text. No HTML, scripts, or arbitrary keys."""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

WEBSITE_SCHEMA = json.loads(Path(__file__).with_name('website_schema.json').read_text())
LANGUAGES = ('ru', 'kk', 'en')


def validate_link(value, relative=False):
    if not value:
        return
    if any(c.isspace() or ord(c) < 32 for c in value) or '\\' in value:
        raise ValueError('В ссылке не должно быть пробелов или обратных слешей')
    if value.startswith('/') and not value.startswith('//') or re.fullmatch(r'#[a-zA-Z0-9_-]+', value):
        return
    parsed = urlsplit(value)
    if relative or parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Укажите путь /страница или публичную ссылку http(s) без пароля')


def validate_email(value):
    if value and not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', value):
        raise ValueError('Проверьте адрес электронной почты')
    return value


def empty_node(schema):
    kind = schema['type']
    if kind in ('object', 'locales'):
        result = {key: empty_node(child) for key, child in schema.get('fields', {}).items()}
        if kind == 'locales':
            result.update({lang: empty_node(schema['item']) for lang in LANGUAGES})
        return result
    if kind == 'list':
        return []
    if kind == 'tuple':
        return [empty_node(child) for child in schema['items']]
    return None if schema.get('nullable') else ''


def validate_node(value, schema, path=''):
    kind = schema['type']
    if kind in ('object', 'locales'):
        if not isinstance(value, dict):
            raise ValueError(f'{path}: ожидаются поля раздела')
        fields = dict(schema.get('fields', {}))
        if kind == 'locales':
            fields.update({lang: schema['item'] for lang in LANGUAGES})
        if set(value) - set(fields):
            raise ValueError(f'{path}: неизвестные поля')
        # New optional fields get a safe blank default during upgrades/import.
        return {key: validate_node(value.get(key, empty_node(child)), child, f'{path} / {child.get("label") or key}') for key, child in fields.items()}
    if kind in ('list', 'tuple'):
        if not isinstance(value, list) or len(value) > schema.get('max', 100):
            raise ValueError(f'{path}: слишком длинный список')
        if kind == 'tuple' and len(value) != len(schema['items']):
            raise ValueError(f'{path}: неверное количество полей ссылки')
        return [validate_node(row, schema['items'][i] if kind == 'tuple' else schema['item'], f'{path} / {i + 1}') for i, row in enumerate(value)]
    if value is None and schema.get('nullable'):
        return None
    if not isinstance(value, str) or len(value) > schema.get('max', 10000) or '\x00' in value:
        raise ValueError(f'{path}: слишком длинный или некорректный текст')
    value = value.strip()
    fmt = schema.get('format')
    if fmt in ('link', 'path'):
        validate_link(value, relative=fmt == 'path')
    if fmt == 'email':
        validate_email(value)
    return value


def validate_page(slug, content):
    if slug not in WEBSITE_SCHEMA:
        raise ValueError('Неизвестная страница сайта')
    if len(json.dumps(content, ensure_ascii=False).encode()) > 600000:
        raise ValueError('Страница превышает допустимый размер')
    return validate_node(content, WEBSITE_SCHEMA[slug]['schema'], WEBSITE_SCHEMA[slug]['label'])
