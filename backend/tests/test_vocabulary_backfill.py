import importlib.util
from pathlib import Path
from sqlalchemy import select
from test_catalog import client,make_type,payload,field
from test_marcsql import ITEM
from app.main import app,db
from app.db import Record,DocumentType


def entries(c,t): return c.get(f'/api/types/{t}/vocabulary').json()
def update(c,t,auto=True):
    return c.put(f'/api/types/{t}',json={'name':'Книга','config':[{'tag':'245','required':True},{'tag':'080','vocabularies':{'a':{'auto_add':auto}}}]})


def test_enable_collects_old_records_preserves_labels_and_type_boundaries(client):
    t=make_type(client)
    p=payload(t);p['marc']['fields'] += [field('080',value=' 378 '),field('080',value='378'),field('080',value='3')]
    r=client.post('/api/records',json=p);assert r.status_code==201,r.text
    before=client.get('/api/records/'+str(r.json()['id'])).json()
    other=client.post('/api/types',json={'name':'Другой','config':[]}).json()['id']
    p=payload(other);p['marc']['fields'].append(field('080',value='999'))
    assert client.post('/api/records',json=p).status_code==201
    assert update(client,t,False).status_code==200
    assert entries(client,t)==[]
    assert client.post(f'/api/types/{t}/vocabulary/080/a',json={'value':'3','label':'Общественные науки'}).status_code==201
    for _ in range(2): assert update(client,t).status_code==200
    assert {e['value']:e['label'] for e in entries(client,t)}=={'3':'Общественные науки','378':''}
    assert client.get('/api/records/'+str(r.json()['id'])).json()==before


def test_import_populates_auto_only_and_preview_is_read_only(client):
    t=client.post('/api/types',json={'name':'Импорт','config':[{'tag':'653','vocabularies':{'a':{'auto_add':True}}},{'tag':'100','vocabularies':{'a':{'auto_add':False}}}]}).json()['id']
    body={'source':'test','doc_id':1,'type_id':t,'rectype':'a','biblevel':'m','item':ITEM,'preview':True}
    assert client.post('/api/import/marcsql',json=body).status_code==200
    assert entries(client,t)==[]
    body['preview']=False
    r=client.post('/api/import/marcsql',json=body);assert r.status_code==200,r.text
    assert {e['value'] for e in entries(client,t)}=={'әдіс','химия'}
    assert client.post('/api/import/marcsql',json=body).json()['status']=='skipped'
    assert len(entries(client,t))==2


def test_upgrade_backfills_multiple_batches_without_touching_records(client,monkeypatch):
    t=make_type(client)
    assert update(client,t).status_code==200
    provider=app.dependency_overrides[db]()
    with next(provider) as s:
        for i in range(251):
            marc=payload(t)['marc'];marc['fields'] += [field('080',value=str(i)),field('080',value='x'*1001),field('080',value='   ')]
            s.add(Record(type_id=t,marc=marc,search_text='unchanged'))
        s.commit()
        path=Path(__file__).parents[1]/'migrations/versions/0014_backfill_vocabularies.py'
        spec=importlib.util.spec_from_file_location('migration_vocab',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        monkeypatch.setattr(module.op,'get_bind',lambda:s.connection())
        module.upgrade();module.upgrade();s.commit()
        assert all(r.search_text=='unchanged' for r in s.scalars(select(Record)))
    provider.close()
    assert len(entries(client,t))==251
