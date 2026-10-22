from collections import Counter

def validate_config(config, dictionary, local_dictionary=None):
    errors=[]; tags=[]
    for c in config:
        tag=c['tag']; tags.append(tag); spec=(local_dictionary or {}).get(tag) if c.get('local') else dictionary.get(tag)
        if not spec: errors.append(f'Unknown tag {tag}'); continue
        allowed={s['code'] for s in spec['subfields']}
        if any(s not in allowed for s in c['subfields']): errors.append(f'{tag}: unknown subfield in profile')
    if len(tags)!=len(set(tags)): errors.append('Duplicate profile fields')
    return errors

def validate_marc(marc, config, dictionary, previous=None):
    errors=[]; warnings=[]
    # MARCSQL exports may leave 245 indicators blank. Preserve only blanks
    # already stored in this record; do not invent cataloguing semantics.
    legacy_blanks=Counter(
        pos for f in (previous or {}).get('fields',[]) if f['tag']=='245'
        for pos in (1,2) if f.get(f'ind{pos}')==' '
    )
    if len(marc['leader'])!=24 or not marc['leader'].isascii(): errors.append('Leader must contain 24 ASCII characters')
    fields=marc['fields']; counts=Counter(f['tag'] for f in fields)
    for c in config:
        if c['tag']=='000': continue
        if c['required'] and not any(f['tag']==c['tag'] and (f.get('value','').strip() or any(s['value'].strip() for s in f.get('subfields',[]))) for f in fields):
            errors.append(f"{c['tag']}: required by document type")
    for f in fields:
        tag=f['tag']; spec=dictionary.get(tag)
        if tag=='000': errors.append('000: маркер хранится в leader, а не в массиве fields'); continue
        if not spec:
            warnings.append(f'{tag}: unknown/local field preserved')
        elif not spec['repeatable'] and counts[tag]>1: errors.append(f'{tag}: not repeatable')
        if spec and spec['obsolete']: warnings.append(f'{tag}: obsolete')
        if int(tag)<10:
            if f.get('value') is None or f.get('subfields') or f.get('ind1') is not None or f.get('ind2') is not None: errors.append(f'{tag}: control field must have only value')
            length={'005':16,'006':18,'008':40}.get(tag)
            if length and len(f.get('value') or '')!=length: errors.append(f'{tag}: expected {length} characters')
            continue
        if f.get('value') is not None or f.get('subfields') is None: errors.append(f'{tag}: data field needs subfields, not value')
        for pos in (1,2):
            v=f.get(f'ind{pos}')
            if v is None or len(v)!=1 or not v.isascii(): errors.append(f'{tag}: indicator {pos} must be one ASCII character'); continue
            options=[x['code'] for ind in (spec or {}).get('indicators',[]) if ind['position']==pos for x in ind['values']]
            if options and v not in options and v!='|':
                if tag=='245' and v==' ' and legacy_blanks[pos]>0:
                    legacy_blanks[pos]-=1
                    warnings.append(f'245: сохранён пустой индикатор {pos} из прежней записи; его можно уточнить в настройках поля «Индикаторы»')
                else:
                    errors.append(f'{tag}: invalid indicator {pos}: {v!r}')
        subs=f.get('subfields') or []; sc=Counter(s['code'] for s in subs)
        for s in subs:
            definition=next((x for x in (spec or {}).get('subfields',[]) if x['code']==s['code']),None)
            if definition and not definition['repeatable'] and sc[s['code']]>1: errors.append(f"{tag}${s['code']}: not repeatable")
            if spec and not definition: warnings.append(f"{tag}${s['code']}: unknown subfield preserved")
    return sorted(set(errors)), sorted(set(warnings))

def search_text(marc):
    return ' '.join([marc['leader']]+[f.get('value') or ' '.join(s['value'] for s in f.get('subfields',[])) for f in marc['fields']]).casefold()
