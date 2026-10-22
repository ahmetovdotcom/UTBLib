from test_catalog import client,field
from app.main import app,db
from app.db import Record,DocumentType


def test_udc_only_prefix_combined_filters_and_pagination(client):
    g=app.dependency_overrides[db]();s=next(g)
    try:
        a=DocumentType(name='Книга',config=[]);b=DocumentType(name='Статья',config=[]);s.add_all([a,b]);s.flush()
        rows=[Record(type_id=tid,search_text=title,marc={'fields':fields}) for tid,title,fields in [
            (a.id,'экономика',[field('080','a',' 336'),field('080','a','378')]),
            (a.id,'экономика',[field('080','a','338')]),
            (a.id,'336 в заглавии',[field('245','a','336'),field('080','b','336')]),
            (b.id,'экономика',[field('080','a','336.1')]),
            (a.id,'другое',[field('080','a','80')]),
        ]]
        s.add_all(rows);s.commit();ids=[r.id for r in rows];type_id=a.id
    finally:g.close()
    result=client.get('/api/records',params={'udc':'33','q':'экономика','type_id':type_id,'limit':1}).json()
    assert [r['id'] for r in result]==[ids[1]]
    result=client.get('/api/records',params={'udc':'33','q':'экономика','type_id':type_id,'limit':1,'offset':1}).json()
    assert [r['id'] for r in result]==[ids[0]]
    assert [r['id'] for r in client.get('/api/records',params={'udc':'378'}).json()]==[ids[0]]
    assert len(client.get('/api/records',params={'udc':'   '}).json())==5
    for value in ['%','_','33%','\\',"' OR 1=1 --"]:
        response=client.get('/api/records',params={'udc':value});assert response.status_code==200,response.text;assert response.json()==[]
