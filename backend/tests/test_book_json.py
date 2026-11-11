import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import book_photos as photos
from app.main import app
from app.security import permission_for
from test_catalog import client, payload
from test_book_photos import make_type, row, extended_type, entry
from test_security import add as add_user, login

URL = '/api/book-photos'


def answer(type_id, fields=None):
    return {'format': photos.JSON_FORMAT, 'type_id': type_id,
            'fields': [row()] if fields is None else fields, 'warnings': []}


def submit(client, type_id, data):
    return client.post(URL + '/import-json', json={'type_id': type_id, 'text': json.dumps(data, ensure_ascii=False)})


@pytest.fixture(autouse=True)
def no_provider(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    async def forbidden(*args, **kwargs):
        raise AssertionError('External JSON must never call a provider')
    monkeypatch.setattr(photos, 'call_openai', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'post', forbidden)


def test_prompt_matches_type_and_omits_operational_fields(client):
    t = extended_type(client)
    entry(client, t, '952$j', '6B06101', 'Ақпараттық жүйелер')
    response = client.get(URL + '/prompt', params={'type_id': t})
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    prompt = response.json()['prompt']
    schema = json.loads(prompt.split('JSON Schema ответа:\n')[1])
    assert schema['properties']['type_id']['const'] == t
    assert schema['properties']['format']['const'] == photos.JSON_FORMAT
    keys = schema['properties']['fields']['items']['properties']['key']['enum']
    assert '245$a' in keys and '952$j' in keys
    assert not {'541$n', '541$h', '097$b', '001'} & set(keys)
    assert '6B06101' in prompt and 'Ақпараттық жүйелер' in prompt
    assert 'КАЗАХСКОМ' in prompt and 'не выдумывай' in prompt
    assert client.get(URL + '/prompt', params={'type_id': 999999}).status_code == 404


@pytest.mark.parametrize('wrap', [lambda s: s, lambda s: '\ufeff ' + s,
                                   lambda s: '```json\n' + s + '\n```', lambda s: '```\n' + s + '\n```'])
def test_import_without_key_is_read_only_and_preserves_repeat_authors(client, wrap):
    t = make_type(client)
    saved = client.post('/api/records', json=payload(t)).json()
    vocab = client.get(f'/api/types/{t}/vocabulary').json()
    data = answer(t, [row(), row('700$a', ['Әуезов, М.', 'Жұмабайұлы, М.'])])
    response = client.post(URL + '/import-json', json={'type_id': t, 'text': wrap(json.dumps(data, ensure_ascii=False))})
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['fields'][0]['values'] == ['Қазақ тілі']
    assert response.json()['fields'][1]['values'] == ['Әуезов, М.', 'Жұмабайұлы, М.']
    assert 'usage' not in response.json()
    current = client.get(f"/api/records/{saved['id']}").json()
    assert current['marc'] == saved['marc'] and current['version'] == saved['version']
    assert client.get(f'/api/types/{t}/vocabulary').json() == vocab
    assert len(client.get('/api/records').json()) == 1


def test_import_uses_current_closed_dictionaries_and_marks_recommendations(client):
    t = extended_type(client)
    entry(client, t, '952$j', '6B06101', 'Ақпараттық жүйелер')
    data = answer(t, [row('041$a', ['unknown']), row('952$j', ['Ақпараттық жүйелер'])])
    response = submit(client, t, data)
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result['fields']) == 1 and result['warnings']
    assert result['fields'][0]['values'] == ['6B06101']
    assert result['fields'][0]['basis'] == 'inferred'
    assert result['fields'][0]['vocabulary_status'] == 'matched'
    assert not any(e['value'] == 'unknown' for e in client.get(f'/api/types/{t}/vocabulary').json())


@pytest.mark.parametrize('change', [
    lambda d: d.update(format='other'), lambda d: d.update(type_id=True), lambda d: d.update(type_id=999999),
    lambda d: d.update(fields=[None]), lambda d: d.update(fields={}), lambda d: d.update(warnings=[{}]),
    lambda d: d['fields'][0].update(key='541$h'), lambda d: d['fields'][0].update(key=[]),
    lambda d: d['fields'][0].update(values=['one', 'two']), lambda d: d['fields'][0].update(values=[123]),
    lambda d: d['fields'][0].update(image_numbers=[True]), lambda d: d['fields'][0].update(image_numbers=[7]),
    lambda d: d['fields'][0].update(evidence=None), lambda d: d['fields'][0].update(unknown='extra'),
    lambda d: d['fields'].append(row()), lambda d: d['fields'][0].pop('basis'),
])
def test_malformed_or_wrong_type_fields_cannot_reach_draft(client, change):
    t = make_type(client)
    data = answer(t); change(data)
    response = submit(client, t, data)
    assert response.status_code == 422, response.text
    assert client.get('/api/records').json() == []


@pytest.mark.parametrize('text', ['', '{', 'Ответ: {}', '{} {}', '{"a":1,"a":2}', 'NaN',
                                  '[' * 2000 + ']' * 2000])
def test_invalid_text_is_safe_422(client, text):
    t = make_type(client)
    response = client.post(URL + '/import-json', json={'type_id': t, 'text': text})
    assert response.status_code == 422


def test_size_and_empty_fields(client, monkeypatch):
    t = make_type(client)
    assert submit(client, t, answer(t, [])).json()['fields'] == []
    assert client.post(URL + '/import-json', json={'type_id': t, 'text': 'x' * (photos.MAX_JSON_TEXT + 1)}).status_code == 413
    monkeypatch.setattr(photos, 'MAX_JSON_BODY', 10)
    assert submit(client, t, answer(t)).status_code == 413


def test_permissions_and_csrf(client):
    t = make_type(client)
    add_user(client, username='jsonviewer', role='viewer', permissions=['catalog.view'])
    assert permission_for('GET', URL + '/prompt') == 'catalog.edit'
    assert permission_for('POST', URL + '/import-json') == 'catalog.edit'
    with TestClient(app) as c:
        assert c.get(URL + '/prompt', params={'type_id': t}).status_code == 401
        assert submit(c, t, answer(t)).status_code == 401
        login(c, 'jsonviewer')
        assert c.get(URL + '/prompt', params={'type_id': t}).status_code == 403
        assert submit(c, t, answer(t)).status_code == 403
    with TestClient(app) as c:
        c.post('/api/auth/login', json={'username': 'admin', 'password': 'test-secret'})
        assert submit(c, t, answer(t)).status_code == 403
