"""Conservative system fields: never reconstruct an imported 008 wholesale."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo
import re

def populate(marc, config, type_name, previous=None, now=None):
    marc=deepcopy(marc); now=now or datetime.now(timezone.utc)
    fields=marc['fields']; old=(previous or {}).get('fields',[])
    configured={c['tag'] for c in config}
    def first(items,tag): return next((f for f in items if f['tag']==tag),None)
    def enabled(tag): return tag in configured or first(fields,tag) is not None or first(old,tag) is not None
    def put(tag,value):
        f=first(fields,tag)
        if f is None: fields.append({'tag':tag,'value':value})
        else: f['value']=value
    if enabled('001'):
        original=first(old,'001'); incoming=first(fields,'001')
        put('001',(original or {}).get('value') or (incoming or {}).get('value') or 'CAT-'+uuid4().hex)
    if enabled('005'):
        stamp=now.strftime('%Y%m%d%H%M%S.')+str(now.microsecond//100000)
        original=(first(old,'005') or {}).get('value','')
        # A revision must remain distinguishable even within the same tenth of a second.
        if re.fullmatch(r'\d{14}\.\d',original) and stamp<=original:
            try: stamp=(datetime.strptime(original,'%Y%m%d%H%M%S.%f')+timedelta(milliseconds=100)).strftime('%Y%m%d%H%M%S.%f')[:16]
            except ValueError: pass
        put('005',stamp)
    old008=(first(old,'008') or {}).get('value','')
    if enabled('008') and (previous is None or old008 or (first(fields,'008') or {}).get('value')):
        incoming=(first(fields,'008') or {}).get('value','')
        if not incoming:
            incoming=old008 or now.astimezone(ZoneInfo('Asia/Almaty')).strftime('%y%m%d')+'|'*34
            if not old008:
                def sub(tag,code):
                    return [s['value'].strip() for f in fields if f['tag']==tag for s in f.get('subfields',[]) if s['code']==code and s['value'].strip()]
                years=sub('260','c') or sub('264','c'); langs=sub('041','a')
                if len(years)==1 and re.fullmatch(r'\d{4}',years[0]): incoming=incoming[:6]+'s'+years[0]+'    '+incoming[15:]
                if len(langs)==1 and re.fullmatch(r'[a-z]{3}',langs[0]): incoming=incoming[:35]+langs[0]+incoming[38:]
        if len(old008)==40 and len(incoming)==40: incoming=old008[:6]+incoming[6:]
        put('008',incoming)
    leader=marc['leader']
    if len(leader)==24 and '000' in configured:
        if previous and len(previous['leader'])==24:
            status=previous['leader'][5]; leader=leader[:5]+('c' if status in ('n','c') else status)+leader[6:]
        elif not previous and leader=='00000nam a2200000   4500':
            leader=leader[:7]+('a' if type_name=='Научная статья' else 'm')+leader[8:]
        marc['leader']=leader
    if any(c['tag']=='990' and c.get('local') for c in config):
        prior=first(old,'990'); current=first(fields,'990')
        if current is None:
            current={'tag':'990','ind1':' ','ind2':' ','subfields':[]}; fields.append(current)
        for code,fmt in [('d','%Y'),('e','%m.%Y'),('f','%d.%m.%Y')]:
            stored=next((s for s in (prior or {}).get('subfields',[]) if s['code']==code),None)
            target=next((s for s in current.get('subfields',[]) if s['code']==code),None)
            # Older records without a known creation date must not acquire today's date.
            if stored is not None: value=stored['value']
            elif previous or ((first(fields,'008') or {}).get('value','')[:6] not in ('',now.astimezone(ZoneInfo('Asia/Almaty')).strftime('%y%m%d'))): continue
            elif target and target['value']: continue  # preserve imported creation metadata
            else: value=now.astimezone(ZoneInfo('Asia/Almaty')).strftime(fmt)
            if target: target['value']=value
            else: current.setdefault('subfields',[]).append({'code':code,'value':value})
    return marc

def validate_coded(marc,previous=None):
    old=next((f.get('value','') for f in (previous or {}).get('fields',[]) if f['tag']=='008'),'')
    value=next((f.get('value','') for f in marc['fields'] if f['tag']=='008'),'')
    if len(value)!=40: return []  # Structural validation reports wrong lengths.
    errors=[]
    for start,end,pattern,label in [(0,6,r'\d{6}','дата создания'),(6,7,r'[bcdeikmnpqrstu|]','характер даты'),(7,11,r'(?:[0-9u ]{4}|\|{4})','первая дата'),(11,15,r'(?:[0-9u ]{4}|\|{4})','вторая дата'),(15,18,r'(?:[a-z]{2}[a-z ]|\|{3})','место издания'),(35,38,r'(?:[a-z]{3}| {3}|\|{3})','язык')]:
        if len(old)==40 and value[start:end]==old[start:end]: continue
        if not re.fullmatch(pattern,value[start:end],flags=re.ASCII): errors.append('008: неверный формат — '+label)
    return errors
