from sqlalchemy import select
from .db import Session, DocumentType
from .worksheet import default_config
from .catalog_vocabularies import configure,seed_literature

def seed():
    with Session() as s:
        for name in ('Книга','Научная статья'):
            if s.scalar(select(DocumentType).where(DocumentType.name==name)): continue
            t=DocumentType(name=name,config=configure(default_config()));s.add(t);s.flush();seed_literature(s,t)
        s.commit()
if __name__=='__main__': seed()
