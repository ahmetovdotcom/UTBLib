"""Explicit local PostgreSQL reset; no source-server driver or network-source configuration."""
import argparse
from sqlalchemy import text,delete,select,func
from .db import (Session,Record,Copy,Acquisition,AcquisitionLine,AcquisitionHistory,Withdrawal,
    CopyHistory,RecordCreation,MarcsqlSource,MarcsqlCopySource)

TABLES=[Withdrawal,AcquisitionHistory,CopyHistory,MarcsqlCopySource,Copy,AcquisitionLine,Acquisition,RecordCreation,MarcsqlSource,Record]

def clear(s):
    if s.bind.dialect.name=='postgresql':
        s.execute(text('LOCK TABLE '+', '.join(m.__tablename__ for m in TABLES)+' IN ACCESS EXCLUSIVE MODE'))
    counts={m.__tablename__:s.scalar(select(func.count()).select_from(m)) for m in TABLES}
    for m in TABLES:s.execute(delete(m))
    return counts

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--confirm',default='')
    args=parser.parse_args()
    with Session() as s:
        url=s.bind.url
        if url.get_backend_name()!='postgresql' or url.host!='db' or url.database!='catalog':
            parser.error('Разрешён только локальный PostgreSQL db/catalog внутри Compose')
        if not args.apply:
            print({m.__tablename__:s.scalar(select(func.count()).select_from(m)) for m in TABLES});return
        if args.confirm!='RESET_LOCAL_CATALOG':parser.error('Нужен --confirm RESET_LOCAL_CATALOG и предварительная резервная копия')
        counts=clear(s);s.commit();print('Очищены только локальные данные:',counts)
        print('Типы документов, настройки полей и справочники сохранены. Последовательности ID не сбрасывались.')

if __name__=='__main__':main()
