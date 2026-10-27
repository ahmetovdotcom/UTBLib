from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.db import Record, VocabularyEntry
from app.main import app, db
from app.validation import search_text
from test_catalog import client, payload, field
from test_security import add as add_user, login

URL = '/api/catalog-attention'


@contextmanager
def session():
    provider = app.dependency_overrides[db]()
    try:
        yield next(provider)
    finally:
        provider.close()


def make_type(client, name='Книга', auto=False, editable=False, vocab=True):
    config = [{'tag': '245', 'required': True}, {'tag': '952', 'local': True, 'subfields': ['e', 'j']}]
    if vocab:
        config[-1]['vocabularies'] = {'j': {'auto_add': auto, 'allow_edit': editable}}
    response = client.post('/api/types', json={'name': name, 'config': config})
    assert response.status_code == 201, response.text
    return response.json()['id']


def saved(type_id, values=(), title='Тест', extra=()):
    # Legacy/imported records can contain values rejected for NEW manual input.
    marc = payload(type_id)['marc']
    marc['fields'][0]['subfields'][0]['value'] = title
    marc['fields'] += [field('952', 'j', v) for v in values] + list(extra)
    with session() as s:
        record = Record(type_id=type_id, marc=marc, search_text=search_text(marc))
        s.add(record);s.commit()
        return record.id


def entry(client, type_id, value):
    response = client.post(f'/api/types/{type_id}/vocabulary/952/j', json={'value': value})
    assert response.status_code == 201, response.text
    return response.json()['id']


def report(client, fields=('952$j',), checks=('missing', 'vocabulary'), **filters):
    params = [('fields', key) for key in fields] + [('checks', key) for key in checks] + list(filters.items())
    response = client.get(URL, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_all_fields_options_and_missing_subfields(client):
    t = make_type(client, vocab=False)
    options = client.get(URL+'/options', params={'type_id': t}).json()['fields']
    by_key = {f['key']: f for f in options}
    assert {'952', '952$j', '952$e', '245$a', '001', '000', '650$a'} <= set(by_key)
    assert by_key['952$j']['label'] == 'Специальность'
    assert by_key['650$a']['configured'] is False
    empty = saved(t, ['', ' \t\u00a0'], extra=[field('952', 'e', 'Кафедра')])
    absent = saved(t)
    present = saved(t, ['', 'Финансы'])
    data = report(client, checks=('missing',))
    assert {r['id'] for r in data['items']} == {empty, absent}
    assert data['total'] == data['counts']['missing'] == 2
    assert data['scanned'] == 3
    assert present not in {r['id'] for r in data['items']}
    assert {r['id'] for r in report(client, fields=('952',), checks=('missing',))['items']} == {absent}
    assert report(client, fields=('000',), checks=('missing',))['total'] == 0
    assert report(client, fields=('001',), checks=('missing',))['total'] == 3


def test_closed_dictionary_legacy_values_and_normalization(client):
    t = make_type(client)
    entry(client, t, 'Йога');entry(client, t, 'Финансы')
    saved(t, [' И\u0306ога ', 'Финансы'])  # NFC + surrounding spaces match the stored term.
    bad = saved(t, ['Ошибка', 'Ошибка', 'Финансы', 'Другое'])
    data = report(client, checks=('vocabulary',))
    assert data['total'] == 1 and data['items'][0]['id'] == bad
    assert data['items'][0]['issues'] == [{'field': '952$j', 'kind': 'vocabulary', 'values': ['Другое', 'Ошибка'], 'allow_edit': False}]
    # Selecting the whole field also checks its configured subfield dictionaries, once.
    assert report(client, fields=('952', '952$j'), checks=('vocabulary',))['items'][0]['issues'] == data['items'][0]['issues']


def test_auto_add_free_input_and_operator_suggestions(client):
    auto = make_type(client, name='Автопополнение', auto=True)
    free = make_type(client, name='Свободный ввод', vocab=False)
    editable = make_type(client, name='Редактирование', editable=True)
    t = next(t for t in client.get('/api/types').json() if t['id'] == editable)
    t['config'].append({'tag':'097','local':True,'vocabularies':{'b':{'auto_add':False,'allow_edit':False}}})
    assert client.put(f'/api/types/{editable}', json={'name':t['name'],'config':t['config']}).status_code == 200
    for t in (auto, free, editable):
        saved(t, ['Новое значение'], extra=[field('097', 'b', 'Прежний оператор')])
    data = report(client, fields=('952$j', '097$b'), checks=('vocabulary',))
    assert data['total'] == 1 and data['items'][0]['type_id'] == editable
    assert data['items'][0]['issues'][0]['allow_edit'] is True
    with session() as s:
        assert s.scalar(select(func.count()).select_from(VocabularyEntry).where(VocabularyEntry.tag == '952', VocabularyEntry.code == 'j')) == 0
        assert list(s.scalars(select(Record.version))) == [1, 1, 1]
    # Automatic dictionaries still participate in the missing-value check.
    missing = saved(auto)
    assert report(client, type_id=auto)['items'][0]['id'] == missing


def test_type_specific_dictionaries_and_settings_recalculated(client):
    a = make_type(client, name='Первый')
    b = make_type(client, name='Второй')
    entry(client, a, 'Финансы')
    saved(a, ['Финансы']);bad = saved(b, ['Финансы'])
    assert report(client)['items'][0]['id'] == bad
    assert report(client, type_id=a)['total'] == 0
    allowed = entry(client, b, 'Финансы')
    assert report(client)['total'] == 0
    assert client.delete(f'/api/types/{b}/vocabulary/{allowed}').status_code == 204
    assert report(client)['total'] == 1
    types = client.get('/api/types').json();t = next(t for t in types if t['id'] == b)
    t['config'][-1]['vocabularies']['j']['auto_add'] = True
    assert client.put(f'/api/types/{b}', json={'name': t['name'], 'config': t['config']}).status_code == 200
    assert report(client)['total'] == 0


def test_any_issue_once_per_record_and_corrected_record_disappears(client):
    t = make_type(client)
    entry(client, t, 'Финансы')
    bad = saved(t, ['Неправильно'])
    result = report(client, fields=('952$j', '020$a'))
    assert result['total'] == 1
    assert result['counts'] == {'missing': 1, 'vocabulary': 1}
    assert len(result['items'][0]['issues']) == 2
    record = client.get('/api/records/'+str(bad)).json()
    record['marc']['fields'][-1]['subfields'][0]['value'] = 'Финансы'
    record['marc']['fields'].append(field('020', 'a', '978-601-04-3364-9'))
    response = client.put('/api/records/'+str(bad), json={k:record[k] for k in ('type_id', 'version', 'marc')})
    assert response.status_code == 200, response.text
    assert report(client, fields=('952$j', '020$a'))['total'] == 0


def test_filter_before_pagination_totals_and_literal_search(client):
    t = make_type(client, vocab=False)
    missing = [saved(t, title='Без специальности') for _ in range(53)]
    for _ in range(8):
        saved(t, ['Финансы'])
    first = report(client, limit=50)
    second = report(client, offset=50, limit=50)
    assert first['total'] == second['total'] == 53
    assert first['scanned'] == 61
    assert [r['id'] for r in first['items']] == list(reversed(missing))[0:50]
    assert [r['id'] for r in second['items']] == list(reversed(missing))[50:]
    assert report(client, q='Финансы')['total'] == 0
    literal = saved(t, title='100%_книга')
    assert report(client, q='%_')['items'][0]['id'] == literal
    assert report(client, q='%_')['total'] == 1


def test_query_validation_and_catalog_permissions(client):
    make_type(client)
    for params in ({}, {'fields':'bogus'}, {'fields':'952$Z'}, {'fields':'952$j', 'checks':'other'}, {'fields':'952$j','offset':-1}, {'fields':'952$j','limit':101}):
        assert client.get(URL, params=params).status_code == 422
    assert client.get(URL+'/options?type_id=999999').status_code == 404
    add_user(client, username='catalogviewer', role='viewer', permissions=['catalog.view'])
    add_user(client, username='nocatalog', role='reader', permissions=['loans.view_own'])
    for username, status in [('catalogviewer', 200), ('nocatalog', 403)]:
        with TestClient(app) as c:
            login(c, username)
            assert c.get(URL, params={'fields':'952$j'}).status_code == status
            assert c.get(URL+'/options').status_code == status
    with TestClient(app) as anonymous:
        assert anonymous.get(URL, params={'fields':'952$j'}).status_code == 401
        assert anonymous.get(URL+'/options').status_code == 401
