"""Prepare type IDs in the application's own PostgreSQL; never contact SQL Server."""
import json
from sqlalchemy import select
from .db import Session,DocumentType
from .worksheet import default_config
from .catalog_vocabularies import configure,seed_literature

NAMES={'a/m':'Книга','a/a':'Научная статья','a/c':'Коллекция','a/s':'Сериальное издание'}
def prepare(s):
    mapping={}
    for key,name in NAMES.items():
        t=s.scalar(select(DocumentType).where(DocumentType.name==name))
        if t is None:
            t=DocumentType(name=name,config=configure(default_config()));s.add(t);s.flush();seed_literature(s,t)
        mapping[key]=t.id
    return mapping

def main():
    with Session() as s:
        mapping=prepare(s);s.commit()
    print(json.dumps(mapping,ensure_ascii=False))
if __name__=='__main__': main()
