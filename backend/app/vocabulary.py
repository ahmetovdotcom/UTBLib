import hashlib,unicodedata
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import VocabularyEntry

def normalized(value): return unicodedata.normalize('NFC',value.strip())
def value_key(value): return hashlib.sha256(normalized(value).encode()).hexdigest()
def add_entry(s,type_id,tag,code,value,label=''):
    value=normalized(value); key=value_key(value)
    query=select(VocabularyEntry).where(VocabularyEntry.type_id==type_id,VocabularyEntry.tag==tag,VocabularyEntry.code==code,VocabularyEntry.value_key==key)
    found=s.scalar(query)
    if found: return found
    try:
        with s.begin_nested():
            found=VocabularyEntry(type_id=type_id,tag=tag,code=code,value=value,label=label.strip(),value_key=key)
            s.add(found);s.flush()
    except IntegrityError:
        found=s.scalar(query)
        if found is None: raise
    return found

def values(marc,tag,code):
    return [v for f in (marc or {}).get('fields',[]) if f['tag']==tag for v in ([f.get('value','')] if code=='_' else [s['value'] for s in f.get('subfields',[]) if s['code']==code]) if v.strip()]

def apply_vocabularies(s,t,marc,previous=None):
    errors=[];warnings=[]
    for config in t.config:
        tag=config['tag']
        for code,settings in config.get('vocabularies',{}).items():
            if (tag,code)==('097','b'): continue  # Employee lookup is a suggestion; retain legacy/manual names.
            prior={value_key(v) for v in values(previous,tag,code)}
            known={e.value_key for e in s.scalars(select(VocabularyEntry).where(VocabularyEntry.type_id==t.id,VocabularyEntry.tag==tag,VocabularyEntry.code==code))}
            for value in values(marc,tag,code):
                key=value_key(value)
                if key in known: continue
                if settings.get('auto_add'):
                    if len(normalized(value))>1000:
                        warnings.append(f'{tag}${code}: значение сохранено в записи, но слишком длинное для справочника (максимум 1000 символов)');continue
                    add_entry(s,t.id,tag,code,value);known.add(key)
                elif not settings.get('allow_edit') and key not in prior: errors.append(f'{tag}${code}: выберите значение из справочника или разрешите ручное редактирование / автопополнение в настройках ввода')
    return errors,warnings
