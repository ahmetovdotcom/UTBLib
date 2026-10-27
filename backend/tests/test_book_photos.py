import asyncio
import base64
import copy
import io
import json

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from test_catalog import client, payload
from app import book_photos as photos
from app.main import app
from test_security import add as add_user, login

URL = '/api/book-photos'


def photo(fmt='PNG', size=(200, 300)):
    buffer = io.BytesIO()
    Image.new('RGB', size, 'white').save(buffer, format=fmt)
    return 'data:image/' + ('jpeg' if fmt == 'JPEG' else fmt.lower()) + ';base64,' + base64.b64encode(buffer.getvalue()).decode()


def make_type(client, auto=False):
    result = client.post('/api/types', json={'name': 'Фото', 'config': [
        {'tag':'245','subfields':['a','b']}, {'tag':'700','subfields':['a']},
        {'tag':'041','local':True,'subfields':['a'],'vocabularies':{'a':{'auto_add':auto}}},
        {'tag':'250','local':True,'subfields':['b']}, {'tag':'952','local':True,'subfields':['j']},
        {'tag':'541','local':True,'subfields':['n','h']},
    ]})
    assert result.status_code == 201, result.text
    return result.json()['id']


def row(key='245$a', values=None):
    return dict(key=key, values=values or ['Қазақ тілі'], image_numbers=[1],
                evidence='Қазақ тілі', confidence='clear', basis='printed')


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')
    seen = []
    response = {'fields':[row()], 'warnings':[]}
    async def fake(images, allowed):
        seen.append((images, allowed))
        return copy.deepcopy(response), photos.response_usage({}, photos.DEFAULT_MODEL)
    monkeypatch.setattr(photos, 'call_openai', fake)
    return response, seen


def test_proposals_do_not_save_and_respect_config(client, provider):
    result, seen = provider
    t = make_type(client)
    saved = client.post('/api/records', json=payload(t)).json()
    response = client.post(URL+'/analyze', json={'type_id':t,'images':[photo(),photo()]})
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['fields'][0]['values'] == ['Қазақ тілі']
    images, allowed = seen[0]
    assert len(images) == 2 and images[0].startswith('data:image/jpeg;base64,')
    assert {'245$a','245$b','700$a','041$a','250$b'} == set(allowed)
    assert not ({'541$n','541$h','952$j','097$b','250$a'} & set(allowed))
    assert client.get('/api/records/'+str(saved['id'])).json()['marc'] == saved['marc']
    assert client.get('/api/records/'+str(saved['id'])).json()['version'] == saved['version']
    assert len(client.get('/api/records').json()) == 1


def test_closed_and_auto_dictionaries_do_not_backfill(client, provider):
    result, seen = provider
    t = make_type(client)
    before = client.get(f'/api/types/{t}/vocabulary').json()
    result['fields'] = [row('041$a', ['kaz'])]
    response = client.post(URL+'/analyze', json={'type_id':t,'images':[photo()]}).json()
    assert response['fields'] == [] and response['warnings']
    assert client.get(f'/api/types/{t}/vocabulary').json() == before
    config = next(x for x in client.get('/api/types').json() if x['id'] == t)
    config['config'][2]['vocabularies']['a']['auto_add'] = True
    assert client.put(f'/api/types/{t}', json={'name':config['name'],'config':config['config']}).status_code == 200
    response = client.post(URL+'/analyze', json={'type_id':t,'images':[photo()]}).json()
    assert response['fields'][0]['vocabulary_status'] == 'new'
    assert response['fields'][0]['warnings']
    assert client.get(f'/api/types/{t}/vocabulary').json() == before
    assert client.get(f'/api/types/{t}/vocabulary').json() == before


@pytest.mark.parametrize('change', [
    lambda r:r['fields'][0].update(key='541$h'),
    lambda r:r['fields'].append(row()),
    lambda r:r['fields'][0].update(values=['one','two']),
    lambda r:r['fields'][0].update(image_numbers=[2]),
    lambda r:r['fields'][0].update(values=[' ']),
])
def test_bad_provider_data_never_reaches_editor(client, provider, change):
    result, _ = provider
    t = make_type(client);change(result)
    response = client.post(URL+'/analyze', json={'type_id':t,'images':[photo()]})
    assert response.status_code == 502
    assert client.get('/api/records').json() == []


def test_bad_photos_types_and_request_limits(client, provider, monkeypatch):
    _, seen = provider
    t = make_type(client)
    for images in ([], [photo()]*7, ['https://example.org/photo.jpg'], ['data:image/jpeg;base64,AAAA'], [photo(size=(10,10))]):
        response = client.post(URL+'/analyze', json={'type_id':t,'images':images})
        assert response.status_code == 422, response.text
        assert 'base64' not in response.text
    assert not seen
    assert client.post(URL+'/analyze', json={'type_id':999999,'images':[photo()]}).status_code == 404
    monkeypatch.setattr(photos, 'MAX_BODY', 20)
    assert client.post(URL+'/analyze', json={'type_id':t,'images':[photo()]}).status_code == 413
    assert not seen


def test_permission_csrf_and_disabled_configuration(client, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    response = client.get(URL+'/config')
    assert response.json() == {'enabled':False,'max_images':6}
    assert 'key' not in response.text.lower()
    assert client.post(URL+'/analyze', json={}).status_code == 503
    add_user(client, username='photoreader', role='viewer', permissions=['catalog.view'])
    with TestClient(app) as c:
        assert c.get(URL+'/config').status_code == 401
        login(c, 'photoreader')
        assert c.get(URL+'/config').status_code == 403
        assert c.post(URL+'/analyze', json={}).status_code == 403
    with TestClient(app) as c:
        c.post('/api/auth/login', json={'username':'admin','password':'test-secret'})
        assert c.post(URL+'/analyze', json={}).status_code == 403


def test_busy_slot_released_on_failure():
    with photos.request_slot(123):
        with pytest.raises(HTTPException) as exc:
            with photos.request_slot(123):
                pass
        assert exc.value.status_code == 429
    assert not photos._inflight
    with pytest.raises(ValueError):
        with photos.request_slot(123):
            raise ValueError()
    assert not photos._inflight


def test_responses_payload_and_no_retry_or_error_leak(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'not-a-real-key')
    allowed = {'245$a': {'key':'245$a','label':'Заглавие','repeatable':False, 'local':True,
        'dictionary':[{'value':'Пример','label':'Пояснение'}], 'dictionary_complete':True, 'allow_new':False}}
    calls = []
    status, response_body = 200, {'status':'completed', 'output':[{'type':'message','content':[
        {'type':'output_text','text':json.dumps({'fields':[row()],'warnings':[]})}]}]}
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['follow_redirects'] is False
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, headers, json):
            calls.append(json)
            assert url == 'https://api.openai.com/v1/responses'
            assert headers['Authorization'] == 'Bearer not-a-real-key'
            return httpx.Response(status, json=response_body)
    monkeypatch.setattr(photos.httpx, 'AsyncClient', Client)
    assert asyncio.run(photos.call_openai([photo()], allowed))[0]['fields'][0]['key'] == '245$a'
    assert calls[-1]['store'] is False and 'tools' not in calls[-1]
    assert calls[-1]['service_tier'] == 'default'
    assert calls[-1]['text']['format']['schema']['properties']['fields']['items']['properties']['key']['enum'] == ['245$a']
    assert calls[-1]['input'][0]['content'][-1]['type'] == 'input_image'
    context = calls[-1]['input'][0]['content'][0]['text']
    assert 'Пример' in context and 'Пояснение' in context and '"allow_new": false' in context
    assert 'basis' in calls[-1]['text']['format']['schema']['properties']['fields']['items']['required']
    for status, code in [(401,503),(429,429),(500,502)]:
        response_body={'error':{'message':'not-a-real-key and sensitive provider details'}}
        before=len(calls)
        with pytest.raises(HTTPException) as error:
            asyncio.run(photos.call_openai([photo()], allowed))
        assert error.value.status_code == code
        assert 'not-a-real-key' not in str(error.value)
        assert len(calls) == before+1


@pytest.mark.parametrize('response_body', [
    {'status':'incomplete','output':[]},
    {'status':'completed','output':[{'type':'message','content':[{'type':'refusal','refusal':'no'}]}]},
    {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'not json'}]}]},
])
def test_incomplete_refusal_and_malformed_response(monkeypatch, response_body):
    monkeypatch.setenv('OPENAI_API_KEY','test')
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): return httpx.Response(200,json=response_body)
    monkeypatch.setattr(photos.httpx,'AsyncClient',Client)
    with pytest.raises(HTTPException):
        asyncio.run(photos.call_openai([photo()], {'245$a':{'key':'245$a'}}))


@pytest.mark.parametrize('kind,status', [('success',200),('empty',200),('incomplete',502),('refusal',422),('malformed',502),('invalid_fields',502)])
def test_api_reports_envelope_usage_even_when_paid_answer_is_unusable(client, monkeypatch, kind, status):
    from test_book_photo_usage import envelope
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')
    response_body = envelope()
    description = {'fields': [row()], 'warnings': []}
    if kind == 'invalid_fields':
        description['fields'][0]['key'] = '541$h'
    if kind == 'empty':
        description['fields'] = []
    content = [{'type':'output_text', 'text': 'not JSON' if kind == 'malformed' else json.dumps(description)}]
    if kind == 'refusal':
        content = [{'type':'refusal', 'refusal':'private provider text'}]
    response_body.update(status='incomplete' if kind == 'incomplete' else 'completed',
                         output=[{'type':'message','content':content}])
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): return httpx.Response(200, json=response_body)
    monkeypatch.setattr(photos.httpx, 'AsyncClient', Client)
    t = make_type(client)
    response = client.post(URL+'/analyze', json={'type_id':t,'images':[photo()]})
    assert response.status_code == status, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['usage']['total_tokens'] == 11000
    assert response.json()['usage']['estimated_cost_usd'] == '0.032'
    assert 'private provider text' not in response.text and 'test-key-not-real' not in response.text
    if status != 200:
        assert 'fields' not in response.json()
    assert client.get('/api/records').json() == []


def test_no_usable_dictionary_does_not_send_request_or_claim_usage(client, provider):
    _, calls = provider
    t = client.post('/api/types', json={'name':'Пустые списки','config':[
        {'tag':'952','local':True,'subfields':['j'],'vocabularies':{'j':{'auto_add':True}}},
    ]}).json()['id']
    response = client.post(URL+'/analyze', json={'type_id':t,'images':[photo()]}).json()
    assert not calls
    assert response['request_sent'] is False and response['usage'] is None


def test_analysis_does_not_block_circulation(client, provider, monkeypatch):
    from app import security
    t = make_type(client)
    def unexpected_lock(*args):
        raise AssertionError('Photo analysis must not lock circulation')
    monkeypatch.setattr(security, 'lock', unexpected_lock)
    response = client.post(URL+'/analyze', json={'type_id':t,'images':[photo()]})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize('value,expected', [
    ('212 p.', '212 с.'), ('212 р.', '212 с.'), ('212 pp.', '212 с.'),
    ('212 pages', '212 с.'), ('212 P.', '212 с.'), ('212 с.', '212 с.'),
    ('XII, 212 p. : ил.', 'XII, 212 с. : ил.'), ('[12] p.', '[12] с.'),
    ('2 т. (212 p.; 305 pp.)', '2 т. (212 с.; 305 с.)'),
    ('1 CD-ROM', '1 CD-ROM'), ('212 pозовых иллюстраций', '212 pозовых иллюстраций'),
])
def test_page_units(value, expected):
    assert photos.normalize_extent(value) == expected


def extended_type(client):
    from app.worksheet import default_config
    cfg = default_config()
    for f in cfg:
        if f['tag'] == '952':
            f['vocabularies'] = {c:{'auto_add':True} for c in ('a','d','e','j')}
        if f['tag'] in ('260','041'):
            f['vocabularies'] = {'a':{'auto_add':False}}
    result = client.post('/api/types', json={'name':'Расширенная книга', 'config':cfg})
    assert result.status_code == 201, result.text
    return result.json()['id']


def entry(client, type_id, key, value, label=''):
    tag, code = key.split('$')
    response = client.post(f'/api/types/{type_id}/vocabulary/{tag}/{code}', json={'value':value,'label':label})
    assert response.status_code == 201, response.text


def test_all_bibliographic_fields_and_exact_directory_choices(client, provider):
    result, seen = provider
    t = extended_type(client)
    for key,value,label in [
        ('952$d','Факультет экономики','Экономические науки'),
        ('952$e','Финансы и учет',''),
        ('952$j','6В04108 — Финансы','Финансы'),
        ('952$a','КУК','Книги учеб. каз.яз.'),
        ('260$a','Алматы','Almaty'), ('041$a','kaz','Казахский')]:
        entry(client,t,key,value,label)
    before = client.get(f'/api/types/{t}/vocabulary').json()
    result['fields'] = [row('300$a',['212 p.']), row('952$d',['факультет экономики']),
        row('952$e',['Финансы и учет']), row('952$j',['Финансы']),
        row('952$a',['Книги учеб. каз.яз.']), row('260$a',['Almaty'])]
    response = client.post(URL+'/analyze',json={'type_id':t,'images':[photo()]})
    assert response.status_code == 200, response.text
    fields = {f['key']:f for f in response.json()['fields']}
    assert fields['300$a']['values'] == ['212 с.']
    assert fields['952$j']['values'] == ['6В04108 — Финансы']
    assert fields['952$d']['values'] == ['Факультет экономики']
    assert fields['952$a']['values'] == ['КУК']
    assert fields['260$a']['values'] == ['Алматы']
    assert fields['952$j']['basis'] == 'inferred'
    assert fields['952$j']['vocabulary_status'] == 'matched'
    allowed = seen[0][1]
    assert {'013$b','245$h','245$z','256$a','336$b','337$b','650$a','773$t','952$j','952$i','500$a'} <= set(allowed)
    assert not {'000','001','005','008','097$b','090$f','541$n','541$h','990$c','990$d','998$a','900$a'} & set(allowed)
    assert allowed['952$j']['allow_new'] is False  # Even with auto_add enabled.
    assert allowed['952$j']['dictionary'] == [{'value':'6В04108 — Финансы','label':'Финансы'}]
    assert client.get(f'/api/types/{t}/vocabulary').json() == before
    assert client.get('/api/records').json() == []


def test_unknown_faculty_and_closed_values_omitted_but_open_values_allowed(client, provider):
    result, _ = provider
    t = extended_type(client)
    entry(client,t,'952$d','Экономика')
    entry(client,t,'260$a','Алматы')
    result['fields'] = [row('952$d',['Несуществующий факультет']), row('260$a',['Другое место']),
                        row('952$i',['Новая дисциплина']), row('245$a',['Новая книга'])]
    response = client.post(URL+'/analyze',json={'type_id':t,'images':[photo()]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert {f['key'] for f in body['fields']} == {'952$i','245$a'}
    assert any('Факультет' in w and 'не добавлено' in w for w in body['warnings'])
    assert any('Кафедра' in w and 'нет значений' in w for w in body['warnings'])
    assert any('Место издания' in w for w in body['warnings'])


def test_dictionary_scoping_and_budget_canonicalizes_using_full_list(client, provider, monkeypatch):
    result, seen = provider
    t = extended_type(client)
    entry(client,t,'260$a','Астана')
    entry(client,t,'260$a','Өскемен','Oskemen')
    entry(client,t,'952$j','6В04108 — Финансы')
    other = client.post('/api/types',json={'name':'Другой тип','config':[{'tag':'952','local':True,'subfields':['j'],'vocabularies':{'j':{'auto_add':True}}}]}).json()['id']
    entry(client,other,'952$j','Чужая специальность')
    monkeypatch.setattr(photos,'MAX_DICTIONARY_ENTRIES',1)
    result['fields'] = [row('260$a',['Oskemen'])]
    response = client.post(URL+'/analyze',json={'type_id':t,'images':[photo()]})
    assert response.status_code == 200, response.text
    assert response.json()['fields'][0]['values'] == ['Өскемен']
    dictionary = seen[0][1]['260$a']
    assert not dictionary['dictionary_complete'] and len(dictionary['dictionary']) == 1
    assert 'Чужая специальность' not in json.dumps(seen[0][1],ensure_ascii=False)
    assert sum(len(json.dumps(e,ensure_ascii=False)) for f in seen[0][1].values() for e in f['dictionary']) <= photos.MAX_DICTIONARY_CHARS


def test_ambiguous_dictionary_labels_are_not_guessed():
    entries = [{'value':'А','label':'Общее'},{'value':'Б','label':'Общее'}]
    assert photos.canonical_value('Общее',entries) is None
    assert photos.canonical_value('А',entries) == 'А'


def test_udc_inference_requires_known_code(client, provider):
    result, _ = provider
    t = extended_type(client)
    result['fields'] = [{**row('080$a',['123.456']), 'basis':'inferred'}]
    response = client.post(URL+'/analyze',json={'type_id':t,'images':[photo()]}).json()
    assert response['fields'] == [] and response['warnings']
    result['fields'][0]['basis'] = 'printed'
    response = client.post(URL+'/analyze',json={'type_id':t,'images':[photo()]}).json()
    assert response['fields'][0]['values'] == ['123.456']
