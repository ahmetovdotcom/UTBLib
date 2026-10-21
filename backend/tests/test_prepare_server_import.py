from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db import Base,DocumentType
from app.prepare_server_import import prepare

def test_import_mapping_uses_actual_ids_and_is_repeatable():
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(DocumentType(id=41,name='Книга',config=[]));s.flush()
        mapping=prepare(s);s.commit()
        assert mapping['a/m']==41
        assert set(mapping)=={'a/m','a/a','a/c','a/s'}
        assert len(set(mapping.values()))==4
        assert prepare(s)==mapping
