import json
import pytest
from app.import_marcsql import load_mapping, main


def test_mapping_from_environment_without_shared_file(monkeypatch):
    monkeypatch.setenv('IMPORT_TYPE_MAP','{"a/m": 1, "a/a": 2}')
    assert load_mapping()=={'a/m':1,'a/a':2}


@pytest.mark.parametrize('raw',['{}','[]','{"a/m": true}','{"a/m": 0}','{"book": 1}','invalid'])
def test_invalid_mapping(monkeypatch,raw):
    monkeypatch.setenv('IMPORT_TYPE_MAP',raw)
    with pytest.raises(ValueError): load_mapping()


def test_explicit_file_overrides_environment(tmp_path,monkeypatch):
    path=tmp_path/'mapping.json'
    path.write_text(json.dumps({'a/m':7}))
    monkeypatch.setenv('IMPORT_TYPE_MAP','{"a/m": 1}')
    assert load_mapping(path)=={'a/m':7}


def test_check_config_without_sql_driver(tmp_path,monkeypatch,capsys):
    monkeypatch.setenv('IMPORT_TYPE_MAP','{"a/m": 1}')
    monkeypatch.setattr('sys.argv',['import','--check-config','--report',str(tmp_path/'report.jsonl')])
    main()
    assert 'Подключения к сети не выполнялись' in capsys.readouterr().out
    assert list(tmp_path.iterdir())==[]


def test_report_without_configuration_or_network(tmp_path,monkeypatch,capsys):
    path=tmp_path/'report.jsonl';path.write_text('{"status":"preview"}\n')
    monkeypatch.delenv('IMPORT_TYPE_MAP',raising=False)
    monkeypatch.setattr('sys.argv',['import','--show-report','--report',str(path)])
    main()
    assert capsys.readouterr().out=='{"status":"preview"}\n'
