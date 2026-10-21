import sys,types
import pytest
from app import import_marcsql_copies as importer
from app import import_marcsql_all as combined

ENV={'MARCSQL_HOST':'unused','MARCSQL_USER':'unused','MARCSQL_PASSWORD':'unused','MARCSQL_DATABASE':'unused','MARCSQL_SOURCE':'test','ADMIN_KEY':'test-secret'}

def test_config_only_never_connects(monkeypatch,tmp_path,capsys):
    for k,v in ENV.items():monkeypatch.setenv(k,v)
    monkeypatch.setattr(sys,'argv',['import','--check-config','--report',str(tmp_path/'report.jsonl')])
    monkeypatch.setitem(sys.modules,'pymssql',None)
    importer.main();assert 'без подключения к сети' in capsys.readouterr().out

def test_network_importer_executes_select_only_and_defaults_to_preview(monkeypatch,tmp_path):
    for k,v in ENV.items():monkeypatch.setenv(k,v)
    executed=[];posted=[]
    class Cursor:
        def execute(self,q,args):executed.append(q);assert q.strip().startswith('SELECT ') and 'dbo.INV' in q
        def fetchall(self):return [{'INV_ID':1,'DOC_ID':3}]
        def close(self):pass
    class Conn:
        def cursor(self):return Cursor()
        def close(self):pass
    def connect(**kwargs):assert kwargs['autocommit'] is True;return Conn()
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'results':[{'inv_id':1,'status':'preview'}]}
    class API:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,path,json):posted.append(json);return Response()
    monkeypatch.setitem(sys.modules,'pymssql',types.SimpleNamespace(connect=connect))
    monkeypatch.setattr(importer.httpx,'Client',API)
    monkeypatch.setattr(sys,'argv',['import','--limit','1','--report',str(tmp_path/'report.jsonl')])
    importer.main();assert len(executed)==1 and posted[0]['preview'] is True

def test_combined_import_stops_before_copies_if_catalog_fails(monkeypatch):
    calls=[]
    def fail():calls.append('catalog');raise SystemExit(1)
    monkeypatch.setattr(combined,'catalogue',fail)
    monkeypatch.setattr(combined,'copies',lambda:calls.append('copies'))
    monkeypatch.setattr(sys,'argv',['all','--apply'])
    with pytest.raises(SystemExit):combined.main()
    assert calls==['catalog']
