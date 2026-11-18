"""Read-only, bounded report builder. Templates contain definitions, never results."""
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func, or_, update, delete
from sqlalchemy.orm import Session
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.worksheet.worksheet import Worksheet
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter

from .db import Record, DocumentType, Copy, AcquisitionLine, Acquisition, KsuEntry, CatalogFile, ReportTemplate, utcnow
from .security import has, require
from .specialties import primary, choices

MAX_RECORDS = 25000
MAX_COPIES = 100000
SOURCES = {'catalog': 'Каталог (включая записи без экземпляров)', 'copies': 'Действующий фонд', 'receipts': 'Поступления по КСУ'}
# key, label, type, scope. MARC fields are also exposed through a dictionary whitelist.
SPECS = [
 ('number','№ п/п','number','result'), ('record_id','ID записи','number','record'),
 ('author','Автор','text','record'), ('title','Заглавие','text','record'),
 ('subtitle','Сведения, относящиеся к заглавию','text','record'), ('language','Язык текста','text','record'),
 ('place','Место издания','text','record'), ('publisher','Издательство','text','record'),
 ('year','Год издания','text','record'), ('udc','УДК','text','record'), ('isbn','ISBN','text','record'),
 ('type','Вид документа','text','record'), ('primary_specialty','Основная специальность','text','record'),
 ('specialties','Все специальности','text','record'), ('faculty','Труды ППС','boolean','record'),
 ('digital','Есть электронный файл','boolean','record'),
 ('inventory','Инвентарный номер','text','copy'), ('barcode','Штрихкод','text','copy'),
 ('sigla','Сигла хранения','text','copy'), ('price','Цена за экземпляр','money','copy'),
 ('currency','Валюта','text','copy'), ('received_on','Дата поступления экземпляра','date','copy'),
 ('source','Источник поступления','text','copy'), ('invoice','Накладная','text','copy'),
 ('status','Статус экземпляра','text','copy'),
 ('ksu','КСУ','text','ksu'), ('ksu_year','Год КСУ','number','ksu'),
 ('ksu_date','Дата регистрации КСУ','date','ksu'),
 ('quantity','Количество экземпляров','number','result'), ('titles','Количество наименований','number','result'),
 ('amount','Сумма','money','result'), ('unpriced','Экземпляров без цены','number','result'),
]
GROUP_KEYS = {'language','year','publisher','type','primary_specialty','sigla','source','currency','ksu','ksu_year','status'}
OPS = {'text': ['contains','equals','starts_with','empty','not_empty'], 'number': ['equals','gte','lte','between','empty','not_empty'],
       'money': ['equals','gte','lte','between','empty','not_empty'], 'date': ['equals','gte','lte','between','empty','not_empty'], 'boolean': ['equals']}
MARC_KEYS = {'author':[('100','a'),('110','a'),('111','a'),('700','a')], 'title':[('245','a')],
 'subtitle':[('245','b')], 'language':[('041','a')], 'place':[('264','a'),('260','a')],
 'publisher':[('264','b'),('260','b')], 'year':[('264','c'),('260','c')], 'udc':[('080','a')], 'isbn':[('020','a')]}

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Column(Strict):
    key: str = Field(max_length=80)
    label: str = Field(default='', max_length=160)

class Condition(Strict):
    key: str = Field(max_length=80)
    operator: str = Field(default='contains', max_length=30)
    value: str = Field(default='', max_length=500)
    end: str = Field(default='', max_length=500)

class Definition(Strict):
    source: Literal['catalog','copies','receipts'] = 'copies'
    layout: Literal['titles','copies','summary'] = 'titles'
    columns: list[Column] = Field(min_length=1,max_length=40)
    filters: list[Condition] = Field(default_factory=list,max_length=20)
    group_by: str = 'primary_specialty'
    sort: str = 'title'
    descending: bool = False
    title: str = Field(default='Отчёт по библиотечному фонду',min_length=1,max_length=160)

class Preview(Strict):
    definition: Definition
    page: int = Field(default=1,ge=1,le=100000)
    page_size: int = Field(default=50,ge=1,le=100)

class TemplateInput(Strict):
    name: str = Field(min_length=1,max_length=120)
    definition: Definition
    version: int | None = Field(default=None,ge=1)


def fields(official, local):
    result = {key: {'key':key,'label':label,'type':kind,'scope':scope,'operators':OPS[kind]} for key,label,kind,scope in SPECS}
    for tag, spec in {**official,**local}.items():
        if int(tag) < 10: continue
        for sf in spec.get('subfields',[]):
            key=f"marc:{tag}${sf['code']}"
            result[key]={'key':key,'label':f"{tag}${sf['code']} · {sf.get('name') or sf.get('label') or spec.get('name') or tag}",
                         'type':'text','scope':'record','operators':OPS['text']}
    return result


def validate(definition, metadata, user):
    keys = [c.key for c in definition.columns]
    if len(set(keys)) != len(keys): raise HTTPException(422,'Каждый столбец можно выбрать только один раз.')
    used = set(keys) | {f.key for f in definition.filters}
    if definition.sort: used.add(definition.sort)
    if definition.layout=='summary': used.add(definition.group_by)
    if used-set(metadata): raise HTTPException(422,'Выберите поля из списка.')
    if definition.source=='receipts' or any(metadata[k]['scope']=='ksu' for k in used): require(user,'ksu.view')
    if definition.layout=='summary':
        if definition.group_by not in GROUP_KEYS: raise HTTPException(422,'Выберите признак группировки из списка.')
        allowed = {definition.group_by,'number','quantity','titles','amount','unpriced'}
        if set(keys)-allowed or definition.sort and definition.sort not in allowed:
            raise HTTPException(422,'В сводке доступны признак группировки и итоговые показатели.')
    for f in definition.filters:
        spec=metadata[f.key]
        if spec['scope']=='result' or f.operator not in spec['operators']: raise HTTPException(422,'Недопустимое условие отбора.')
        if f.operator in ('empty','not_empty'): continue
        if not f.value.strip(): raise HTTPException(422,'Заполните значение условия.')
        convert(f.value,spec['type'])
        if f.operator=='between':
            if not f.end.strip() or convert(f.value,spec['type'])>convert(f.end,spec['type']):
                raise HTTPException(422,'Проверьте начало и конец диапазона.')
    return definition


def convert(value, kind):
    try:
        if kind in ('number','money'):
            result=Decimal(str(value).replace(',','.'))
            if not result.is_finite(): raise ValueError()
            return result
        if kind=='date': return date.fromisoformat(str(value))
        if kind=='boolean':
            if value not in ('true','false',True,False): raise ValueError()
            return value in ('true',True)
        return str(value).strip().casefold()
    except (ValueError,InvalidOperation): raise HTTPException(422,'Проверьте число, дату или значение «Да / Нет» в условии.') from None


def values(marc, pairs):
    out=[]
    for tag,code in pairs:
        for field in marc.get('fields',[]):
            if field.get('tag')==tag:
                for sf in field.get('subfields',[]):
                    value=str(sf.get('value','')).strip()
                    if sf.get('code')==code and value and value not in out: out.append(value)
    return out


def record_values(row, raw_keys):
    marc=row.marc
    result={key:values(marc,pairs) for key,pairs in MARC_KEYS.items()}
    result.update(record_id=row.id,type=row.type_name,primary_specialty=primary(marc,row.primary_specialty),
                  specialties=choices(marc),faculty=row.is_faculty_work,digital=row.digital)
    for key in raw_keys:
        tag,code=key[5:].split('$');result[key]=values(marc,[(tag,code)])
    return result


def matches(item, conditions, metadata):
    for f in conditions:
        raw=item.get(f.key)
        vals=raw if isinstance(raw,list) else [raw]
        vals=[v for v in vals if v is not None and v!='']
        if f.operator=='empty': ok=not vals
        elif f.operator=='not_empty': ok=bool(vals)
        else:
            kind=metadata[f.key]['type'];needle=convert(f.value,kind)
            def compare(value):
                value=convert(value,kind)
                if f.operator=='equals': return value==needle
                if f.operator=='contains': return needle in value
                if f.operator=='starts_with': return value.startswith(needle)
                if f.operator=='gte': return value>=needle
                if f.operator=='lte': return value<=needle
                return needle<=value<=convert(f.end,kind)
            ok=any(compare(v) for v in vals)
        if not ok: return False
    return True


def display(value):
    if value is None: return ''
    if isinstance(value,bool): return 'Да' if value else 'Нет'
    if isinstance(value,list): return '; '.join(display(v) for v in value)
    if isinstance(value,(date,datetime)): return value.isoformat()
    if isinstance(value,Decimal): return format(value,'.2f')
    return str(value)


def unique(items,key):
    out=[]
    for item in items:
        raw=item.get(key);vals=raw if isinstance(raw,list) else [raw]
        for v in vals:
            if v is not None and v!='' and v not in out: out.append(v)
    return out[0] if len(out)==1 else out or None


def totals(items):
    amounts=defaultdict(Decimal)
    copies=[item for item in items if item.get('_copy') is not None]
    for item in copies:
        if item['price'] is not None: amounts[item['currency']]+=item['price']
    return {'titles':len({item['record_id'] for item in items}), 'quantity':len(copies),
            'unpriced':sum(item['price'] is None for item in copies),
            'amounts':dict(sorted(amounts.items()))}


def collect(s, definition, metadata):
    record_rows=s.execute(select(Record.id, Record.marc, Record.primary_specialty, Record.is_faculty_work,
        DocumentType.name.label('type_name'), select(CatalogFile.id).where(CatalogFile.record_id==Record.id).exists().label('digital'))
        .join(DocumentType,DocumentType.id==Record.type_id).order_by(Record.id).limit(MAX_RECORDS+1)).all()
    if len(record_rows)>MAX_RECORDS: raise HTTPException(422,'Каталог превышает лимит конструктора: 25 000 записей. Нужна расширенная серверная обработка.')
    raw_keys={c.key for c in definition.columns}|{f.key for f in definition.filters}|{definition.sort}
    raw_keys={k for k in raw_keys if k.startswith('marc:')}
    record_filters=[f for f in definition.filters if metadata[f.key]['scope']=='record']
    copy_filters=[f for f in definition.filters if metadata[f.key]['scope'] in ('copy','ksu')]
    records={row.id:record_values(row,raw_keys) for row in record_rows}
    records={key:r for key,r in records.items() if matches(r,record_filters,metadata)}
    # Explicit scalar projection: never fetch digital file payloads through ORM relationships.
    q=(select(Copy.id,func.coalesce(Copy.record_id,AcquisitionLine.record_id).label('record_id'),
        Copy.inventory_number,Copy.barcode,Copy.sigla,Copy.unit_price,Copy.currency,Copy.received_on,Copy.source,Copy.invoice,Copy.status,
        Copy.line_id,AcquisitionLine.unit_price.label('line_price'),AcquisitionLine.currency.label('line_currency'),
        KsuEntry.id.label('ksu_id'),KsuEntry.number,KsuEntry.year,KsuEntry.registered_on)
        .outerjoin(AcquisitionLine,Copy.line_id==AcquisitionLine.id)
        .outerjoin(Acquisition,Acquisition.id==AcquisitionLine.acquisition_id)
        .outerjoin(KsuEntry,Copy.ksu_entry_id==KsuEntry.id)
        .where(or_(Copy.line_id.is_(None),Acquisition.status=='posted')))
    if definition.source=='receipts': q=q.where(Copy.status!='cancelled',KsuEntry.id.is_not(None))
    else: q=q.where(Copy.status=='active')
    copies=s.execute(q.order_by(Copy.id).limit(MAX_COPIES+1)).all()
    if len(copies)>MAX_COPIES: raise HTTPException(422,'Выборка превышает лимит конструктора: 100 000 экземпляров. Нужна расширенная серверная обработка.')
    items=[];seen=set()
    for c in copies:
        if c.record_id not in records: continue
        item={**records[c.record_id], '_copy':c.id,'inventory':c.inventory_number,'barcode':c.barcode,'sigla':c.sigla,
              'price':c.line_price if c.line_id is not None else c.unit_price,
              'currency':c.line_currency if c.line_id is not None else c.currency,
              'received_on':c.received_on,'source':c.source,'invoice':c.invoice,
              'status':{'active':'В фонде','withdrawn':'Списан','cancelled':'Отменён'}.get(c.status,c.status),
              'ksu':f'{c.number}/{c.year}' if c.ksu_id else None,'ksu_year':c.year,'ksu_date':c.registered_on}
        if matches(item,copy_filters,metadata): items.append(item);seen.add(c.record_id)
    if definition.source=='catalog' and not copy_filters:
        items.extend({**r,'_copy':None} for key,r in records.items() if key not in seen)
    return items


def build(s, definition, metadata):
    items=collect(s,definition,metadata)
    summary=totals(items)
    groups=defaultdict(list)
    for item in items:
        key=(item['record_id'] if definition.layout=='titles' else
             display(item.get(definition.group_by)) if definition.layout=='summary' else
             ('copy',item['_copy']) if item['_copy'] is not None else ('record',item['record_id']))
        groups[key].append(item)
    rows=[]
    multiple_currencies=len({item.get('currency') for item in items if item.get('_copy') is not None})>1
    keys={c.key for c in definition.columns}|{definition.sort}
    for members in groups.values():
        t=totals(members);amounts=t.pop('amounts')
        amount=next(iter(amounts.values())) if len(amounts)==1 and not multiple_currencies else '; '.join(f'{display(v)} {k}' for k,v in amounts.items()) or None
        row={key:unique(members,key) for key in keys}
        # Different prices/currencies must not look like a single unit price.
        if 'price' in keys:
            prices=sorted({(display(m.get('price')),m.get('currency','')) for m in members if m.get('_copy') is not None})
            row['price']=(members[0].get('price') if len(prices)==1 and not multiple_currencies else
                          '; '.join(f'{p or "без цены"} {c}' for p,c in prices))
        row.update(t,amount=amount,_record_id=members[0]['record_id'] if definition.layout!='summary' else None)
        rows.append(row)
    if definition.sort and definition.sort!='number':
        key=definition.sort
        present=[r for r in rows if r.get(key) is not None];missing=[r for r in rows if r.get(key) is None]
        def sort_key(r):
            value=r.get(key)
            return (0,value) if isinstance(value,(int,Decimal)) else (1,display(value).casefold())
        rows=sorted(present,key=sort_key,reverse=definition.descending)+missing
    for n,row in enumerate(rows,1): row['number']=n
    currencies=sorted({item['currency'] for item in items if item.get('_copy') is not None})
    columns=[{'key':c.key,'label':c.label.strip() or metadata[c.key]['label']+(f', {currencies[0]}' if c.key in ('price','amount') and len(currencies)==1 else '')} for c in definition.columns]
    return {'columns':columns,'rows':rows,'total':len(rows),'totals':summary,'generated_at':datetime.now(timezone.utc).isoformat()}


def run(s,definition,metadata):
    # A stable snapshot without blocking circulation writes; SQLite tests reuse their isolated connection.
    if s.bind.dialect.name=='postgresql':
        with Session(s.get_bind().execution_options(isolation_level='REPEATABLE READ')) as snapshot:
            return build(snapshot,definition,metadata)
    return build(s,definition,metadata)


def serialize(result):
    return {**result,'rows':[{k: (v if isinstance(v,(int,bool)) or v is None else display(v)) for k,v in row.items()} for row in result['rows']],
            'totals':{**result['totals'],'amounts':{k:display(v) for k,v in result['totals']['amounts'].items()}}}


def workbook(result, definition, metadata):
    book=Workbook(write_only=True);sheet=book.create_sheet('Отчёт')
    columns=result['columns']
    def cell_value(cell,value):
        if isinstance(value,(int,Decimal,date)) and not isinstance(value,bool):
            cell.value=value
            if isinstance(value,Decimal): cell.number_format='#,##0.00'
            elif isinstance(value,date): cell.number_format='dd.mm.yyyy'
        else:
            text=display(value)
            # XML-invalid controls and Excel's per-cell limit are handled explicitly.
            text=''.join(c for c in text if ord(c)>=32 or c in '\t\n\r')
            cell.value=text[:32767];cell.data_type='s'
    thin=Side(style='thin',color='B5C5CA')
    border=Border(left=thin,right=thin,top=thin,bottom=thin)
    align=Alignment(vertical='top',wrap_text=True)
    for i,col in enumerate(columns,1): sheet.column_dimensions[get_column_letter(i)].width=45 if col['key'] in ('title','subtitle','author') else 23
    sheet.freeze_panes='B2'
    sheet.auto_filter.ref=f'A1:{get_column_letter(len(columns))}{len(result["rows"])+1}'
    sheet.print_title_rows='1:1'
    sheet.sheet_properties.pageSetUpPr.fitToPage=True;sheet.page_setup.orientation='landscape';sheet.page_setup.paperSize=Worksheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth=1;sheet.page_setup.fitToHeight=0
    header=[]
    for col in columns:
        cell=WriteOnlyCell(sheet);cell_value(cell,col['label']);cell.border=border;cell.alignment=align
        cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='163B4A');header.append(cell)
    sheet.append(header)
    for row in result['rows']:
        cells=[]
        for col in columns:
            cell=WriteOnlyCell(sheet);cell_value(cell,row.get(col['key']));cell.border=border;cell.alignment=align;cells.append(cell)
        sheet.append(cells)
    info=book.create_sheet('Параметры и итоги')
    lines=[('Название',definition.title),('Источник',SOURCES[definition.source]),('Вид таблицы',{'titles':'По наименованиям','copies':'По экземплярам','summary':'Сводка'}[definition.layout]),
           ('Сформировано (UTC)',result['generated_at']),('Строк',result['total']),('Наименований (уникальных)',result['totals']['titles']),
           ('Экземпляров',result['totals']['quantity']),('Экземпляров без цены',result['totals']['unpriced'])]
    lines += [(f'Сумма известных цен, {currency}',amount) for currency,amount in result['totals']['amounts'].items()]
    if definition.layout=='summary': lines.append(('Группировка',metadata[definition.group_by]['label']))
    operator_labels={'contains':'Содержит','equals':'Равно','starts_with':'Начинается с','empty':'Не заполнено','not_empty':'Заполнено','gte':'Не меньше / не раньше','lte':'Не больше / не позже','between':'В диапазоне'}
    lines += [(metadata[f.key]['label'],f'{operator_labels[f.operator]}: {f.value}'+(f' — {f.end}' if f.operator=='between' else '')) for f in definition.filters]
    lines += [('Правила','Каталог и фонд: только действующие экземпляры. Поступления по КСУ: включая списанные, без отменённых. Количество из MARC не используется.'),
              ('Суммы','Пустая цена не равна нулю. Итоги включают только известные цены, отдельно по валютам. Наименования в разных группах могут повторяться; общий итог уникален.'),
              ('Специальности','Группировка использует только основную специальность. Все специальности доступны для отбора и отображения без удвоения экземпляров.'),
              ('Длинные ячейки','Текст длиннее 32 767 символов ограничивается форматом Excel; для больших перечней используйте вид «По экземплярам».')]
    info.column_dimensions['A'].width=36;info.column_dimensions['B'].width=110
    for label,value in lines:
        left=WriteOnlyCell(info);right=WriteOnlyCell(info)
        cell_value(left,label);cell_value(right,value);right.alignment=align;info.append([left,right])
    stream=BytesIO();book.save(stream);return stream.getvalue()


def make_router(auth,db,official,local):
    router=APIRouter(prefix='/api/reports');metadata=fields(official,local)
    @router.get('/fields')
    def options(user=Depends(auth)):
        visible=[f for f in metadata.values() if f['scope']!='ksu' or has(user,'ksu.view')]
        return {'fields':visible,'sources':[{ 'key':k,'label':v} for k,v in SOURCES.items() if k!='receipts' or has(user,'ksu.view')],
                'groups':[k for k in metadata if k in GROUP_KEYS and (metadata[k]['scope']!='ksu' or has(user,'ksu.view'))]}
    @router.post('/preview')
    def preview(body:Preview,user=Depends(auth),s=Depends(db)):
        validate(body.definition,metadata,user);result=run(s,body.definition,metadata)
        start=(body.page-1)*body.page_size;result['rows']=result['rows'][start:start+body.page_size]
        return serialize(result)
    @router.post('/export')
    def export(body:Definition,user=Depends(auth),s=Depends(db)):
        validate(body,metadata,user);result=run(s,body,metadata)
        return Response(workbook(result,body,metadata),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition':'attachment; filename="library-report.xlsx"'})
    def output(t): return {'id':t.id,'name':t.name,'definition':t.definition,'version':t.version,'updated_at':t.updated_at}
    @router.get('/templates')
    def templates(user=Depends(auth),s=Depends(db)):
        return [output(t) for t in s.scalars(select(ReportTemplate).where(ReportTemplate.user_id==user.id).order_by(ReportTemplate.name,ReportTemplate.id))]
    @router.post('/templates',status_code=201)
    def create(body:TemplateInput,user=Depends(auth),s=Depends(db)):
        validate(body.definition,metadata,user)
        if not body.name.strip(): raise HTTPException(422,'Укажите название шаблона.')
        if s.scalar(select(func.count()).select_from(ReportTemplate).where(ReportTemplate.user_id==user.id))>=100: raise HTTPException(422,'Можно сохранить не более 100 шаблонов.')
        t=ReportTemplate(user_id=user.id,name=body.name.strip(),definition=body.definition.model_dump());s.add(t);s.commit();return output(t)
    @router.put('/templates/{id}')
    def edit(id:int,body:TemplateInput,user=Depends(auth),s=Depends(db)):
        validate(body.definition,metadata,user)
        if not body.name.strip(): raise HTTPException(422,'Укажите название шаблона.')
        result=s.execute(update(ReportTemplate).where(ReportTemplate.id==id,ReportTemplate.user_id==user.id,ReportTemplate.version==body.version)
            .values(name=body.name.strip(),definition=body.definition.model_dump(),version=ReportTemplate.version+1,updated_at=utcnow()))
        if result.rowcount!=1: raise HTTPException(409,'Шаблон изменён или удалён. Обновите список шаблонов.')
        s.commit();return output(s.get(ReportTemplate,id))
    @router.delete('/templates/{id}',status_code=204)
    def remove(id:int,version:int,user=Depends(auth),s=Depends(db)):
        result=s.execute(delete(ReportTemplate).where(ReportTemplate.id==id,ReportTemplate.user_id==user.id,ReportTemplate.version==version))
        if result.rowcount!=1: raise HTTPException(409,'Шаблон изменён или удалён. Обновите список шаблонов.')
        s.commit();return Response(status_code=204)
    return router
