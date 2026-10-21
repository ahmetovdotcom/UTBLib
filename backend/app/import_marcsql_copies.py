"""Explicit network importer for INV. Source SQL is fixed SELECT only."""
import argparse
from collections import Counter
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import httpx

# All inventory columns are retained in the source archive, including unknown local fields.
SOURCE_QUERY=('SELECT TOP (%s) i.*, s.SHORTNAME AS _SIGLA_SHORTNAME '
              'FROM dbo.INV AS i LEFT JOIN dbo.SIGLAS AS s ON s.ID=i.SIGLA_ID '
              'WHERE i.INV_ID > %s ORDER BY i.INV_ID')

def json_value(value):
    if isinstance(value,Decimal):return str(value)
    raise TypeError(f'Неизвестный тип исходного значения: {type(value).__name__}')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--limit',type=int,default=3,help='0 = все строки INV, включая пропуски в отчёте')
    parser.add_argument('--after',type=int,default=-2147483649)
    parser.add_argument('--report',default='/import/copies-report.jsonl')
    parser.add_argument('--check-config',action='store_true')
    parser.add_argument('--show-report',action='store_true')
    args=parser.parse_args()
    if args.show_report:
        with open(args.report,encoding='utf-8') as f:
            for line in f:print(line,end='')
        return
    if args.limit<0:parser.error('--limit должен быть неотрицательным')
    for key in ['MARCSQL_HOST','MARCSQL_USER','MARCSQL_PASSWORD','MARCSQL_DATABASE','MARCSQL_SOURCE','ADMIN_KEY']:
        if not os.getenv(key):parser.error(f'Не задана переменная {key}')
    with tempfile.TemporaryFile(dir=Path(args.report).parent) as f:f.write(b'check');f.flush()
    if args.check_config:
        print('Настройки импортёра экземпляров проверены без подключения к сети.');return
    import pymssql
    conn=pymssql.connect(server=os.environ['MARCSQL_HOST'],port=os.getenv('MARCSQL_PORT','1433'),
        user=os.environ['MARCSQL_USER'],password=os.environ['MARCSQL_PASSWORD'],database=os.environ['MARCSQL_DATABASE'],
        charset='UTF-8',tds_version='7.4',autocommit=True,login_timeout=10,timeout=60,as_dict=True)
    cursor=conn.cursor();count=0;totals=Counter()
    try:
        with httpx.Client(base_url=os.getenv('IMPORT_API_URL','http://api:8000'),headers={'X-Admin-Key':os.environ['ADMIN_KEY']},timeout=180) as api,open(args.report,'a',encoding='utf-8') as report:
            while args.limit==0 or count<args.limit:
                size=min(100,args.limit-count) if args.limit else 100
                cursor.execute(SOURCE_QUERY,(size,args.after));rows=cursor.fetchall()
                if not rows:break
                rows=json.loads(json.dumps(rows,ensure_ascii=False,default=json_value,allow_nan=False))
                response=api.post('/api/import/marcsql-copies',json={'source':os.environ['MARCSQL_SOURCE'],'rows':rows,'preview':not args.apply})
                response.raise_for_status();results=response.json()['results']
                if len(results)!=len(rows):raise RuntimeError('API вернул неполный отчёт; повторите запуск с начала')
                for result in results:
                    totals[result['status']]+=1;report.write(json.dumps(result,ensure_ascii=False)+'\n')
                report.flush();count+=len(rows);args.after=rows[-1]['INV_ID']
                print(f'Обработано строк INV: {count}; создано: {totals["created"]}; уже были: {totals["unchanged"]}; пропущено: {totals["skipped"]}; ошибок: {totals["error"]}',flush=True)
    finally:cursor.close();conn.close()
    print(f'Итоги: {dict(totals)}. Отчёт: {args.report}')
    if totals['error']:raise SystemExit(1)

if __name__=='__main__':main()
