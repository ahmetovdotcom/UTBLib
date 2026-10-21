"""Optional integration test. Only run against the disposable test stack, never production."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import httpx
import pytest

@pytest.mark.skipif(os.getenv('ACQUISITIONS_TEST_URL')!='http://localhost:8097',reason='Requires disposable PostgreSQL test stack on localhost:8097')
def test_simultaneous_network_retries():
    base=os.environ['ACQUISITIONS_TEST_URL']+'/api'
    def api(path,body=None):
        with httpx.Client(base_url=base,timeout=30) as c:
            login=c.post('/auth/login',json={'username':'admin','password':'test-secret'});login.raise_for_status()
            c.headers['X-CSRF-Token']=login.json()['csrf_token']
            r=c.get(path) if body is None else c.post(path,json=body)
            r.raise_for_status();return r.json()
    body={'request_key':str(uuid4()),'type_id':1,'initial_acquisition':{'received_on':'2026-10-20','currency':'KZT'},
          'marc':{'leader':'00000nam a2200000   4500','fields':[
              {'tag':'245','ind1':'1','ind2':'0','subfields':[{'code':'a','value':'Параллельный тест '+str(uuid4())}]},
              {'tag':'541','ind1':'1','ind2':' ','subfields':[{'code':'n','value':'10'},{'code':'h','value':'5000'}]},
              {'tag':'990','ind1':' ','ind2':' ','subfields':[{'code':'w','value':'УТБ'}]}]}}
    with ThreadPoolExecutor(max_workers=6) as pool: rows=list(pool.map(lambda _:api('/records',body),range(6)))
    assert len({r['id'] for r in rows})==1
    record_id=rows[0]['id'];assert api(f'/records/{record_id}/copies')['total']==10
    party={'request_key':str(uuid4()),'invoice':'25','source':'Другая организация','received_on':'2026-10-20',
           'lines':[{'record_id':record_id,'quantity':5,'unit_price':'6000','currency':'KZT'}]}
    with ThreadPoolExecutor(max_workers=6) as pool: receipts=list(pool.map(lambda _:api('/acquisitions',party),range(6)))
    assert len({r['id'] for r in receipts})==1
    assert api(f'/records/{record_id}/copies')['total']==15
