"""Explicit administrative operation: replace profiles for all document types.
Run once when adopting the MARCSQL worksheet. Back up the database first.
Normal service startup never calls this module or overwrites edited profiles.
"""
import argparse,json
from pathlib import Path
from sqlalchemy import select
from .db import Session,DocumentType
from .worksheet import default_config

def updated_config(previous):
    old={c['tag']:c for c in previous}
    config=default_config()
    for c in config:
        if 'vocabularies' in old.get(c['tag'],{}):
            c['vocabularies']=old[c['tag']]['vocabularies']
    return config

def apply(backup_path):
    with Session() as session:
        types=list(session.scalars(select(DocumentType).order_by(DocumentType.id)))
        before=[{'id':t.id,'name':t.name,'config':t.config} for t in types]
        with Path(backup_path).open('x') as f: json.dump(before,f,ensure_ascii=False,indent=2)
        for t in types:t.config=updated_config(t.config)
        session.commit()
        return len(types)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--backup',required=True);a=p.parse_args()
    print(f'Updated {apply(a.backup)} document types; backup: {a.backup}')
