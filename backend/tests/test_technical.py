from datetime import datetime,timezone
from copy import deepcopy
from app.technical import populate
from app.worksheet import default_config

NOW=datetime(2026,10,20,4,30,12,123456,tzinfo=timezone.utc)
def record():return {'leader':'00000nam a2200000   4500','fields':[]}
def val(m,tag):return next(f['value'] for f in m['fields'] if f['tag']==tag)
def test_generated_fields_and_dates():
    m=populate(record(),default_config(),'Книга',now=NOW)
    assert val(m,'001').startswith('CAT-')
    assert val(m,'005')=='20261020043012.1'
    assert val(m,'008')=='261020'+'|'*34
    assert next(f for f in m['fields'] if f['tag']=='990')['subfields'][-1]['value']=='20.10.2026'
    assert populate(record(),default_config(),'Научная статья',now=NOW)['leader'][7]=='a'
    assert val(populate(record(),default_config(),'Книга',now=NOW),'001')!=val(m,'001')
def test_existing_identity_creation_and_unknown_positions_survive():
    original=populate(record(),default_config(),'Книга',now=NOW)
    original['fields'].append({'tag':'999','ind1':' ','ind2':' ','subfields':[{'code':'a','value':'  keep  '}]})
    original['fields'][2]['value']='990101s1999    kz '+'x'*17+'rus'+' d'
    assert len(val(original,'008'))==40
    edited=deepcopy(original)
    next(f for f in edited['fields'] if f['tag']=='001')['value']='tampered'
    next(f for f in edited['fields'] if f['tag']=='008')['value']='000000'+val(original,'008')[6:35]+'kaz'+val(original,'008')[38:]
    result=populate(edited,default_config(),'Книга',original,NOW)
    assert val(result,'001')==val(original,'001')
    assert val(result,'005')>val(original,'005')
    assert val(result,'008')[:35]==val(original,'008')[:35]
    assert val(result,'008')[35:38]=='kaz'
    assert result['fields'][-1]==original['fields'][-1]
    assert result['leader'][5]=='c'
def test_imported_values_and_unknown_creation_date():
    m=record();m['fields']=[{'tag':'001','value':'original-id'},{'tag':'008','value':'010203'+'|'*34}]
    result=populate(m,default_config(),'Книга',now=NOW)
    assert val(result,'001')=='original-id';assert val(result,'008').startswith('010203')
    old=record();result=populate(old,default_config(),'Книга',old,NOW)
    assert not next(f for f in result['fields'] if f['tag']=='990')['subfields']
def test_initial_008_uses_only_unambiguous_data():
    m=record();m['fields']=[{'tag':'260','subfields':[{'code':'c','value':'2026'}]},{'tag':'041','subfields':[{'code':'a','value':'kaz'}]}]
    result=populate(m,default_config(),'Книга',now=NOW)
    assert val(result,'008')[6:15]=='s2026    ';assert val(result,'008')[35:38]=='kaz'

def test_invalid_changed_codes_rejected_without_rejecting_legacy_positions():
    from app.technical import validate_coded
    m=populate(record(),default_config(),'Книга',now=NOW)
    next(f for f in m['fields'] if f['tag']=='008')['value']='261020sabcd'+val(m,'008')[11:]
    assert validate_coded(m)
    assert validate_coded(m,m)==[]
