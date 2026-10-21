"""Explicitly invoked network importer. Default is preview, never writes to SQL Server."""
import argparse
import json
import os
import re
import tempfile
from pathlib import Path
import httpx


def load_mapping(path=None):
    raw=Path(path).read_text(encoding='utf-8') if path else os.environ.get('IMPORT_TYPE_MAP','')
    mapping=json.loads(raw)
    if (not isinstance(mapping,dict) or not mapping or
        any(not re.fullmatch(r'./.',key) or type(value) is not int or value<1
            for key,value in mapping.items())):
        raise ValueError('Нужна карта RECTYPE/BIBLEVEL → положительный ID типа документа')
    return mapping


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='Сохранить записи; без флага только просмотр')
    parser.add_argument('--limit',type=int,default=3,help='Максимум записей; 0 = весь каталог')
    parser.add_argument('--after',type=int,default=-2147483649,help='Читать DOC_ID больше указанного')
    parser.add_argument('--mapping',help='Необязательный файл вместо IMPORT_TYPE_MAP')
    parser.add_argument('--report',default='/import/report.jsonl')
    parser.add_argument('--check-config',action='store_true',help='Проверить настройки и папку отчётов без сети')
    parser.add_argument('--show-report',action='store_true',help='Показать отчёт без подключения к базе')
    args=parser.parse_args()
    if args.show_report:
        try:
            with open(args.report,encoding='utf-8') as report:
                for line in report: print(line,end='')
        except OSError:
            parser.error('Отчёт пока отсутствует или недоступен')
        return
    if args.limit<0: parser.error('--limit должен быть неотрицательным')
    try:
        mapping=load_mapping(args.mapping)
        with tempfile.TemporaryFile(dir=Path(args.report).parent) as probe:
            probe.write(b'check');probe.flush()
    except (OSError,ValueError) as exc:
        parser.error(f'Не удалось прочитать настройки или открыть папку отчётов: {exc}')
    if args.check_config:
        print('Настройки типов и запись отчётов проверены. Подключения к сети не выполнялись.')
        return
    import pymssql
    # No credentials in logs or URL; source queries are fixed SELECTs only.
    connection=pymssql.connect(
        server=os.environ['MARCSQL_HOST'],port=os.getenv('MARCSQL_PORT','1433'),
        user=os.environ['MARCSQL_USER'],password=os.environ['MARCSQL_PASSWORD'],
        database=os.environ['MARCSQL_DATABASE'],charset='UTF-8',tds_version='7.4',
        login_timeout=10,timeout=60,as_dict=True)
    count=0
    failures=0
    cursor=connection.cursor()
    try:
        with httpx.Client(base_url=os.getenv('IMPORT_API_URL','http://api:8000'),
                          headers={'X-Admin-Key':os.environ['ADMIN_KEY']},timeout=60) as api, \
             open(args.report,'a',encoding='utf-8') as report:
            while args.limit==0 or count<args.limit:
                size=min(100,args.limit-count) if args.limit else 100
                cursor.execute(
                    'SELECT TOP (%s) DOC_ID, RECTYPE, BIBLEVEL, CAST(ITEM AS nvarchar(max)) AS ITEM '
                    'FROM dbo.DOC WHERE DOC_ID > %s ORDER BY DOC_ID',(size,args.after))
                rows=cursor.fetchall()
                if not rows: break
                for row in rows:
                    key=f"{row['RECTYPE']}/{row['BIBLEVEL']}"
                    type_id=mapping.get(key)
                    if type_id is None:
                        result={'doc_id':row['DOC_ID'],'status':'error','error':f'Нет типа для {key}'}
                        failures+=1
                    else:
                        response=api.post('/api/import/marcsql',json={
                            'source':os.environ['MARCSQL_SOURCE'],'doc_id':row['DOC_ID'],
                            'rectype':row['RECTYPE'],'biblevel':row['BIBLEVEL'],'item':row['ITEM'],
                            'type_id':type_id,'preview':not args.apply})
                        if response.is_success:
                            result=response.json()
                        else:
                            result={'doc_id':row['DOC_ID'],'status':'error','error':response.text}
                            failures+=1
                    report.write(json.dumps(result,ensure_ascii=False)+'\n');report.flush()
                    print(f"DOC_ID={row['DOC_ID']}: {result['status']}",flush=True)
                    args.after=row['DOC_ID'];count+=1
    finally:
        cursor.close();connection.close()
    print(f'Обработано: {count}; ошибок: {failures}. Отчёт: {args.report}')
    if failures: raise SystemExit(1)


if __name__=='__main__':
    main()
