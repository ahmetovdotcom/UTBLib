import pytest
from test_catalog import client, make_type
from app.marcsql import parse_item

ITEM = ('000  \x1f0     n  2 22      i 450 \x1e'
        '001  \x1f\\\\10.0.1.9\\dbf\\invbook\\118782\x1f0RU/IS/BASE/795122011\x1e'
        '005  \x1f020261006164835.6\x1e'
        '008  \x1f0191119|||||||||kz |||||||||||||||||rus||\x1e'
        '1001 \x1faМельдешов А.А.\x1e'
        '245  \x1faФизико-химические методы анализа\x1e'
        '653  \x1faәдіс\x1faхимия\x1e'
        '5411 \x1fn26 экз\x1e'
        '990  \x1ff29.09.2026')


def test_parse_preserves_order_repeat_unicode_and_dates():
    marc,warnings=parse_item(ITEM,'a','m')
    fields=marc['fields']
    assert len(marc['leader'])==24
    assert marc['leader'][6:8]=='am'
    assert fields[0]['value']=='RU/IS/BASE/795122011'
    assert fields[1]['value']=='20261006164835.6'
    assert fields[3]['ind1']=='1'
    assert fields[5]['subfields']==[{'code':'a','value':'әдіс'},{'code':'a','value':'химия'}]
    assert fields[-1]['subfields'][0]['value']=='29.09.2026'
    assert len(warnings)==2


@pytest.mark.parametrize('item',['garbage','245  text','245  \x1f','245  \x1f!bad','001  \x1fa123'])
def test_unsupported_format_rejected(item):
    with pytest.raises(ValueError): parse_item(item,'a','m')


def test_preview_import_idempotence_source_conflict_and_auth(client):
    t=make_type(client)
    body=dict(source='test',doc_id=3,type_id=t,rectype='a',biblevel='m',item=ITEM)
    assert client.post('/api/import/marcsql',json=body,headers={'X-Admin-Key':'wrong'}).status_code==401
    preview=client.post('/api/import/marcsql',json=body)
    assert preview.status_code==200,preview.text
    assert preview.json()['status']=='preview'
    assert client.get('/api/records').json()==[]
    body['preview']=False
    saved=client.post('/api/import/marcsql',json=body).json()
    assert saved['status']=='imported'
    record=client.get(f"/api/records/{saved['record_id']}").json()
    assert record['marc']==preview.json()['marc']
    assert client.get(f"/api/records/{saved['record_id']}/marcsql-source").json()['item']==ITEM
    assert client.post('/api/import/marcsql',json=body).json()['status']=='skipped'
    body['item']+='changed'
    assert client.post('/api/import/marcsql',json=body).status_code==409
    assert len(client.get('/api/records').json())==1
