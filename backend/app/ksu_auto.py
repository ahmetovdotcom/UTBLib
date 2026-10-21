"""Automatic receipt accounting; unclassified data is reported, never guessed."""
import re
from decimal import Decimal
from sqlalchemy import select,func
from .db import KsuEntry,KsuRule,Acquisition,AcquisitionLine,Record
from .acquisitions import lock_request

DEFAULT_RULES={}
def add(code,label,kind='',language='',media=''):
    DEFAULT_RULES[code.upper()]={'code':code.upper(),'label':label,'kind':kind,'language':language,'media':media}
for suffix,language,name in [('И','foreign','иностранный'),('К','kaz','казахский'),('Р','rus','русский')]:
    for prefix,kind,label in [('КН','science','Научные книги'),('КУ','study','Учебные книги'),('КХ','fiction','Художественные книги'),('КС','','Справочные книги'),('ДК','','Дискеты / кассеты')]:
        add(prefix+suffix,label+' · '+name,kind,language)
for suffix,language in [('К','kaz'),('Р','rus')]:add('КУМ'+suffix,'Учебно-методические книги','study',language)
for suffix,language in [('ин.яз.','foreign'),('каз.яз.','kaz'),('рус.яз.','rus')]:
    for prefix,label,kind,media in [('CD','CD-ROM','','cd'),('АДИС','Авторефераты / диссертации','',''),('АУД','Аудио','','audio'),('ВИД','Видео','','video'),('Бр.','Брошюры','',''),('МИ','Методические издания','study','')]:
        term=suffix
        if language=='foreign' and prefix in ('Бр.','МИ'):term='иностр.яз.'
        if language=='foreign' and prefix=='ВИД':term='инос.яз.'
        add(prefix+'/'+term,label,kind,language,media)

def norm(v):return re.sub(r'\s+','',v).upper().replace('А/ДИС','АДИС')
def rules(s):
    result={norm(k):dict(v,version=0) for k,v in DEFAULT_RULES.items()}
    for row in s.scalars(select(KsuRule)):result[row.code]={'code':row.code,**row.settings,'version':row.version}
    return result

def vals(marc,tag,code):
    return {sf['value'].strip() for f in marc.get('fields',[]) if f['tag']==tag for sf in f.get('subfields',[]) if sf['code']==code and sf['value'].strip()}

def classify(marc,mapping):
    problems=[];codes=vals(marc,'952','a');matched=[]
    for code in sorted(codes):
        rule=mapping.get(norm(code))
        if rule:matched.append(rule)
        else:problems.append('Не настроен код 952$a «'+code+'» — настройте соответствие')
    def one(items,what):
        items=set(items)-{''}
        if len(items)>1:problems.append('Противоречивые значения: '+what);return ''
        return next(iter(items),'')
    kinds={r['kind'] for r in matched}
    if '' in kinds:problems.append('Для кода 952$a не назначена категория КСУ в настройках')
    kind=one(kinds,'вид литературы')
    if not kind:
        # Explicit descriptions may fill a missing accounting category, not override conflicting codes.
        labels={'учебная литература':'study','учебник':'study','учебное пособие':'study','учебно-методическая литература':'study','научная литература':'science','художественная литература':'fiction','көркем әдебиет':'fiction'}
        if not codes:kind=one({labels[v.lower()] for v in vals(marc,'952','c') if v.lower() in labels},'952$c')
    if not kind:problems.append('Не определён вид литературы — проверьте 952$a / 952$c')
    lang_codes=vals(marc,'041','a');langs=[]
    for v in lang_codes:
        v=v.lower()
        if v in ('kaz','rus'):langs.append(v)
        elif re.fullmatch('[a-z]{3}',v) and v not in ('und','mul','zxx'):langs.append('foreign')
        else:problems.append('Неоднозначный код языка 041$a «'+v+'»')
    langs += [r['language'] for r in matched]
    language=one(langs,'язык 041$a и 952$a')
    if not language:problems.append('Не определён язык — проверьте 041$a / 952$a')
    udc=vals(marc,'080','a');sectors=[]
    for v in udc:
        # Compound classification belongs to the leading main UDC class; auxiliary-only values require correction.
        if re.match(r'^[01356789]',v):sectors.append(v[0])
        else:problems.append('Нет графы первого листа для УДК «'+v+'»')
    sector=one(sectors,'отрасль УДК')
    if not sector:problems.append('Не определена отрасль — проверьте 080$a')
    media=one([r['media'] for r in matched],'носитель АВД')
    return {'balance':True,'kind':kind,'language':language,'sector':sector,'media':media},list(dict.fromkeys(problems))

def ensure_entry(s,a):
    """Run inside the acquisition transaction, never on a report GET."""
    old=s.scalar(select(KsuEntry).where(KsuEntry.acquisition_id==a.id))
    if old:return old
    year=a.received_on.year;lock_request(s,'ksu-number:',year)
    number=(s.scalar(select(func.max(KsuEntry.number)).where(KsuEntry.year==year)) or 0)+1
    entry=KsuEntry(acquisition_id=a.id,acquisition_version=a.version or 1,year=year,number=number,
        registered_on=a.received_on,document_on=a.document_on or a.received_on,version=1,
        snapshot={'mode':'automatic','source':a.source,'invoice':a.invoice,'lines':[]})
    s.add(entry);s.flush();return entry

def automatic_report(s,year,columns):
    mapping=rules(s)
    pairs=list(s.execute(select(KsuEntry,Acquisition).join(Acquisition,Acquisition.id==KsuEntry.acquisition_id).where(KsuEntry.year==year,Acquisition.status=='posted').order_by(KsuEntry.number)))
    ids=[a.id for _,a in pairs];by_id={}
    if ids:
        for l,r in s.execute(select(AcquisitionLine,Record).join(Record,Record.id==AcquisitionLine.record_id).where(AcquisitionLine.acquisition_id.in_(ids),AcquisitionLine.quantity>0).order_by(AcquisitionLine.id)):
            by_id.setdefault(l.acquisition_id,[]).append((l,r))
    rows=[];totals={c['key']:Decimal(0) if c['key'].endswith('_amount') else 0 for c in columns};issue_count=0
    for e,a in pairs:
        m={c['key']:0 for c in columns};amount=Decimal(0);sets={};issues=[];unknown_price=0;lines=[]
        for l,r in by_id.get(a.id,[]):
            cl,errors=classify(r.marc,mapping)
            if l.unit_price is None:errors.append('Не указана цена в поступлении');unknown_price+=l.quantity
            elif l.currency!='KZT':errors.append('Цена поступления не в тенге: '+l.currency);unknown_price+=l.quantity
            else:amount+=l.unit_price*l.quantity
            for key in ('on_titles','titles','titles_check'):sets.setdefault(key,set()).add(r.id)
            for key in ('copies','on_copies'):m[key]+=l.quantity
            if cl['kind']:sets.setdefault(cl['kind']+'_titles',set()).add(r.id)
            if cl['kind'] and cl['language']:
                m[cl['kind']+'_'+cl['language']]+=l.quantity;m['kind_total']+=l.quantity
            if cl['language']:m['language_'+cl['language']]+=l.quantity
            if cl['sector']:m['sector_'+cl['sector']]+=l.quantity;m['sector_total']+=l.quantity
            if cl['media']:sets.setdefault('media_'+cl['media'],set()).add(r.id)
            title=' '.join(sorted(vals(r.marc,'245','a'))) or l.title_snapshot
            if errors:issues.append({'record_id':r.id,'title':title,'messages':errors})
            lines.append({'line_id':l.id,'record_id':r.id,'title':title,'quantity':l.quantity,**cl})
        m.update({k:len(v) for k,v in sets.items()});m['on_amount']=format(amount,'.2f');m['off_amount']='0.00'
        cancelled=a.status!='posted'
        if not cancelled:
            for k,v in m.items():totals[k]+=Decimal(v) if k.endswith('_amount') else v
            issue_count+=len(issues)
        rows.append({'id':e.id,'acquisition_id':a.id,'number':e.number,'year':e.year,'registered_on':e.registered_on.isoformat(),
            'document_on':a.document_on.isoformat() if a.document_on else None,'received_on':a.received_on.isoformat(),
            'source':a.source,'invoice':a.invoice,'status':'cancelled' if cancelled else ('incomplete' if issues else 'current'),
            'metrics':m,'lines':lines,'issues':issues,'unpriced_count':unknown_price})
    return {'year':year,'columns':columns,'rows':rows,'totals':{k:format(v,'.2f') if isinstance(v,Decimal) else v for k,v in totals.items()},
        'issue_count':issue_count,'stale_count':0,'unpriced_count':sum(r['unpriced_count'] for r in rows if r['status']!='cancelled')}
