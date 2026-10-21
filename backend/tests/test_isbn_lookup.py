import asyncio
import httpx
import pytest
from test_catalog import client
from app.isbn_lookup import normalize,lookup


def test_isbn_validation_and_auth(client):
    assert normalize('0-306-40615-2')=='9780306406157'
    assert normalize('978 0306406157')=='9780306406157'
    for bad in ['9780306406158','123','978030640615X','http://localhost','9780306406157x']:
        with pytest.raises(ValueError): normalize(bad)
    assert client.get('/api/isbn-lookup?isbn=bad').status_code==422
    assert client.get('/api/isbn-lookup?isbn=9780306406157',headers={'X-Admin-Key':'bad'}).status_code==401


def test_lookup_matches_edition_and_partial_failure(monkeypatch):
    async def get(self,url,**kwargs):
        if 'openlibrary' in url: raise httpx.ReadTimeout('timeout')
        return httpx.Response(200,request=httpx.Request('GET',url),json={'items':[
            {'id':'one','volumeInfo':{'title':'Physics','authors':['A','B'],'publisher':'Publisher','publishedDate':'1980','pageCount':123,'industryIdentifiers':[{'identifier':'0306406152'}]}},
            {'id':'wrong','volumeInfo':{'title':'Wrong edition','industryIdentifiers':[{'identifier':'9780140328721'}]}}
        ]})
    monkeypatch.setattr(httpx.AsyncClient,'get',get)
    result=asyncio.run(lookup('9780306406157'))
    assert len(result['items'])==1 and len(result['warnings'])==1
    rows=result['items'][0]['rows']
    assert next(r for r in rows if r['tag']=='700')['value']=='B'
    assert not any(r['tag']=='245' and r['code']=='c' for r in rows)


def test_openlibrary_empty_google_and_read_only(client,monkeypatch):
    async def get(self,url,**kwargs):
        data={'ISBN:9780306406157':{'title':'Test','authors':[{'name':'Author'}],'publishers':[{'name':'Publisher'}],'publish_places':[{'name':'Place'}],'publish_date':'1980','number_of_pages':100}} if 'openlibrary' in url else {}
        return httpx.Response(200,request=httpx.Request('GET',url),json=data)
    monkeypatch.setattr(httpx.AsyncClient,'get',get)
    r=client.get('/api/isbn-lookup?isbn=0306406152')
    assert r.status_code==200
    assert len(r.json()['items'])==1
    assert r.json()['items'][0]['source']=='Open Library'
    assert client.get('/api/records').json()==[]
