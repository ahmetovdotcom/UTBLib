from app.worksheet import default_config, definitions
from app.apply_worksheet import updated_config
from test_catalog import client


def test_new_screenshot_order_and_preserved_dictionary_settings():
    config=default_config()
    assert [c['tag'] for c in config][:30]==[
        '000','001','005','008','013','020','040','041','080','090','097','100',
        '700','245','246','250','256','260','300','440','520','541','653','650',
        '856','900','901','952','990','998']
    by_tag={c['tag']:c for c in config}
    assert by_tag['090']['subfields']==['a','f','c','x']
    assert by_tag['245']['subfields'][:6]==['a','h','b','c','n','p']
    assert by_tag['952']['subfields']==['a','b','c','d','e','i','j']
    assert by_tag['990']['subfields']==['c','d','e','f','g','w','a','b']
    assert by_tag['653']['subfields']==['a']
    before=[{'tag':'080','vocabularies':{'a':{'auto_add':True}}}]
    assert next(c for c in updated_config(before) if c['tag']=='080')['vocabularies']==before[0]['vocabularies']
    assert definitions({})['090']['subfields'][2]['label']=='Каталожный индекс'


def test_manual_990_values_and_auto_dates(client):
    config=default_config()
    next(c for c in config if c['tag']=='990')['vocabularies']={'c':{'auto_add':True}}
    t=client.post('/api/types',json={'name':'Новый лист','config':config})
    assert t.status_code==201,t.text
    body={'type_id':t.json()['id'],'marc':{'leader':'00000nam a2200000   4500','fields':[
        {'tag':'245','ind1':'1','ind2':'0','subfields':[{'code':'a','value':'Тест'}]},
        {'tag':'990','ind1':' ','ind2':' ','subfields':[{'code':'c','value':'Н-123'},{'code':'b','value':'Договор'}]}
    ]}}
    saved=client.post('/api/records',json=body)
    assert saved.status_code==201,saved.text
    record=saved.json()
    f=next(f for f in record['marc']['fields'] if f['tag']=='990')
    values={s['code']:s['value'] for s in f['subfields']}
    assert values['c']=='Н-123' and values['b']=='Договор'
    assert all(values[c] for c in 'def')
    for s in f['subfields']:
        if s['code']=='c': s['value']='Н-456'
        if s['code']=='d': s['value']='1900'
    updated=client.put('/api/records/'+str(record['id']),json={k:record[k] for k in ('type_id','version','marc')})
    assert updated.status_code==200,updated.text
    actual={s['code']:s['value'] for f in updated.json()['marc']['fields'] if f['tag']=='990' for s in f['subfields']}
    assert actual['c']=='Н-456' and actual['d']==values['d']
