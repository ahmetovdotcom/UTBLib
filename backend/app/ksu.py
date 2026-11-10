"""Automatic KSU report and shared literature-code settings."""
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from .db import Acquisition, AcquisitionLine, Record, KsuEntry, KsuHistory, Copy
from .acquisitions import Strict, lock_request, digest, copy_output
from .ksu_data import entries_query, entry_output, member_query

KINDS={'science':'Научные','study':'Учебные','fiction':'Художественные'}
LANGUAGES={'kaz':'Государственный (казахский)','rus':'Русский','foreign':'Иностранный'}
SECTORS={'0':'Общий отдел (0, 004, 006, 008)','1':'Философия. Психология (1)','3':'Общественные науки (3)','5':'Математика и естественные науки (5)','6':'Медицина. Техника. Сельское хозяйство (6)','7':'Искусство. Фотография. Музыка. Игры. Спорт (7)','8':'Языкознание. Филология. Художественная литература (8)','9':'География. Биография. История (9)'}
MEDIA={'':'Не АВД','audio':'Аудио','video':'Видео','cd':'CD'}

class RuleInput(Strict):
    code: str=Field(min_length=1,max_length=120)
    version: int=Field(ge=0)
    label: str=Field(default='',max_length=255)
    kind: Literal['','science','study','fiction']=''
    language: Literal['','kaz','rus','foreign']=''
    media: Literal['','audio','video','cd']=''

class EntryInput(Strict):
    number: int=Field(ge=1,le=2147483647,strict=True)
    year: int=Field(ge=1900,le=9999,strict=True)
    registered_on: date
    document_on: date|None=None
    source: str=Field(default='',max_length=255)
    invoice: str=Field(default='',max_length=255)
    note: str=Field(default='',max_length=4000)

class EntryCreate(EntryInput):
    request_key: UUID

class EntryEdit(EntryInput):
    version: int=Field(ge=1)
    reason: str=Field(min_length=1,max_length=4000)

def serialize(e,a):
    return {'id':e.id,'acquisition_id':e.acquisition_id,'acquisition_version':e.acquisition_version,'version':e.version,
            'number':e.number,'year':e.year,'registered_on':e.registered_on.isoformat(),'document_on':e.document_on.isoformat(),
            'status':'cancelled' if a.status!='posted' else ('stale' if a.version!=e.acquisition_version else 'current'),**e.snapshot}

# Columns mirror Sheet1; Y and AH are explicit check totals instead of unlabeled cells.
def columns():
    out=[('on_titles','Принято на баланс','Наименования'),('on_copies','Принято на баланс','Экземпляры'),('on_amount','Принято на баланс','Сумма, ₸'),
         ('off_titles','Не принято на баланс','Наименования'),('off_copies','Не принято на баланс','Экземпляры'),('off_amount','Не принято на баланс','Сумма, ₸'),
         ('titles','Всего','Наименования'),('copies','Всего','Экземпляры')]
    for k,label in KINDS.items():
        out.append((k+'_titles',label,'Наименования'))
        out.extend((k+'_'+lang,label,name+' · экз.') for lang,name in LANGUAGES.items())
    out.append(('kind_total','По видам','Всего экземпляров'))
    out.extend(('sector_'+k,'По отраслям · экз.',v) for k,v in SECTORS.items())
    out.extend([('sector_total','По отраслям','Всего экземпляров'),('titles_check','Из общего количества','Наименования')])
    out.extend(('language_'+k,'По языкам · экз.',v) for k,v in LANGUAGES.items())
    out.extend(('media_'+k,'АВД · наименования',v) for k,v in MEDIA.items() if k)
    return [{'key':k,'group':g,'label':l} for k,g,l in out]

def metrics(lines):
    result={c['key']:0 for c in columns()};sets={};amounts={'on_amount':Decimal(0),'off_amount':Decimal(0)}
    for l in lines:
        q=l['quantity'];rid=l['record_id'];prefix='on' if l['balance'] else 'off'
        for key in (prefix+'_titles','titles',l['kind']+'_titles','titles_check'):
            sets.setdefault(key,set()).add(rid)
        if l['media']:sets.setdefault('media_'+l['media'],set()).add(rid)
        for key in (prefix+'_copies','copies',l['kind']+'_'+l['language'],'kind_total','sector_'+l['sector'],'sector_total','language_'+l['language']):result[key]+=q
        amounts[prefix+'_amount']+=Decimal(l['unit_price'])*q
    result.update({k:len(v) for k,v in sets.items()})
    result.update({k:format(v,'.2f') for k,v in amounts.items()})
    return result

def report(s,year):
    from .ksu_auto import automatic_report
    return automatic_report(s,year,columns())

def make_router(auth,db):
    router=APIRouter(prefix='/api/ksu',dependencies=[Depends(auth)])

    @router.get('/options')
    def options():return {'kinds':KINDS,'languages':LANGUAGES,'sectors':SECTORS,'media':MEDIA}

    @router.get('/rules')
    def get_rules(s=Depends(db)):
        from .ksu_auto import rules
        return {'items':list(rules(s).values())}

    @router.put('/rules')
    def put_rule(body:RuleInput,s=Depends(db)):
        from .ksu_auto import norm
        from .db import KsuRule
        code=norm(body.code)
        if not code:raise HTTPException(422,'Введите код литературы')
        lock_request(s,'ksu-rule:',code)
        existing=s.get(KsuRule,code)
        if (existing.version if existing else 0)!=body.version:raise HTTPException(409,'Соответствие изменено. Обновите страницу.')
        if not existing:existing=KsuRule(code=code);s.add(existing)
        existing.version=body.version+1
        existing.settings=body.model_dump(exclude={'code','version'})
        s.commit()
        return {'code':code,'version':existing.version,**existing.settings}

    @router.post('/entries',status_code=201)
    def create_entry(body:EntryCreate,s=Depends(db),user=Depends(auth)):
        key=str(body.request_key);hashed=digest(body.model_dump(mode='json'))
        lock_request(s,'ksu-create:',key)
        old=s.scalar(select(KsuEntry).where(KsuEntry.request_key==key))
        if old:
            if old.payload_hash!=hashed:raise HTTPException(409,'Операция создания КСУ уже выполнена с другими данными')
            return entry_output(old)
        lock_request(s,'ksu-number:',body.year)
        e=KsuEntry(**body.model_dump(exclude={'request_key'}),request_key=key,payload_hash=hashed,
            version=1,snapshot={'mode':'copies'})
        try:
            s.add(e);s.flush()
            s.add(KsuHistory(entry_id=e.id,actor_id=user.id,reason='Создание КСУ',before={},after=entry_output(e)))
            s.commit()
        except IntegrityError:
            s.rollback();raise HTTPException(409,'КСУ с таким номером и годом уже существует')
        return entry_output(e)

    @router.put('/entries/{id}')
    def edit_entry(id:int,body:EntryEdit,s=Depends(db),user=Depends(auth)):
        lock_request(s,'ksu-number:',body.year)
        e=s.scalar(entries_query().where(KsuEntry.id==id))
        if not e:raise HTTPException(404,'КСУ не найдена или отменена')
        if e.version!=body.version:raise HTTPException(409,'КСУ изменена. Откройте актуальную версию.')
        before=entry_output(e)
        for k,v in body.model_dump(exclude={'version','reason'}).items():setattr(e,k,v)
        e.version+=1
        try:
            s.flush()
            s.add(KsuHistory(entry_id=e.id,actor_id=user.id,reason=body.reason,before=before,after=entry_output(e)))
            s.commit()
        except IntegrityError:
            s.rollback();raise HTTPException(409,'КСУ с таким номером и годом уже существует')
        return entry_output(e)

    @router.get('/entries/{id}/specialties')
    def get_allocations(id:int,s=Depends(db)):
        from .specialties import entry_allocations
        return entry_allocations(s,id)

    @router.get('/entries/{id}/copies')
    def entry_copies(id:int,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),s=Depends(db)):
        e=s.get(KsuEntry,id)
        if not e:raise HTTPException(404,'КСУ не найдена')
        stmt=member_query([id])
        total=s.scalar(select(func.count()).select_from(stmt.subquery()))
        from .ksu_auto import vals
        items=[]
        for c,line,r in s.execute(stmt.order_by(Copy.id).offset(offset).limit(limit)):
            receipt=s.get(Acquisition,line.acquisition_id) if line else None
            items.append({**copy_output(c,line,receipt),'title':' '.join(sorted(vals(r.marc,'245','a')))})
        return {'entry':entry_output(e),'total':total,'items':items}

    @router.get('/report')
    def get_report(year:int=Query(...,ge=1900,le=9999),s=Depends(db)):return report(s,year)

    @router.get('/departments/report',include_in_schema=False)
    @router.get('/specialties/report')
    def specialties_report(date_from:date,date_to:date,s=Depends(db)):
        if date_from>date_to:raise HTTPException(422,'Начало периода позже окончания')
        from .ksu_specialties import report as specialty_report
        return specialty_report(s,date_from,date_to)

    @router.get('/departments/export',include_in_schema=False)
    @router.get('/specialties/export')
    def specialties_export(date_from:date,date_to:date,s=Depends(db)):
        if date_from>date_to:raise HTTPException(422,'Начало периода позже окончания')
        from .ksu_specialties import report as specialty_report,export_xlsx
        data=specialty_report(s,date_from,date_to)
        if data['total']['unpriced_count']:raise HTTPException(409,'Укажите цены в тенге в поступлениях перед выгрузкой.')
        return Response(export_xlsx(data),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition':f'attachment; filename="ksu-specialties-{date_from}-{date_to}.xlsx"'})

    @router.get('/history/{id}')
    def history(id:int,s=Depends(db)):
        return [{'created_at':h.created_at,'reason':h.reason,'actor_id':h.actor_id,'before':h.before,'after':h.after} for h in s.scalars(select(KsuHistory).where(KsuHistory.entry_id==id).order_by(KsuHistory.id))]

    @router.get('/export')
    def export(year:int=Query(...,ge=1900,le=9999),s=Depends(db)):
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter
        data=report(s,year)
        if data['issue_count']:raise HTTPException(409,'В исходных данных есть неполные или противоречивые сведения. Исправьте указанные карточки, поступления или соответствия перед выгрузкой.')
        w=Workbook();ws=w.active;ws.title='КСУ — поступления'
        cols=data['columns'];width=4+len(cols)
        ws.cell(1,1,f'Книга суммарного учёта. Поступления за {year} год · суммы в тенге');ws.merge_cells(start_row=1,start_column=1,end_row=1,end_column=width)
        for i,t in enumerate(['Дата записи','№ записи по порядку','Источник поступления','Дата сопроводительного документа'],1):
            ws.cell(2,i,t);ws.merge_cells(start_row=2,start_column=i,end_row=3,end_column=i)
        start=5
        while start<=width:
            group=cols[start-5]['group'];end=start
            while end<width and cols[end-4]['group']==group:end+=1
            ws.cell(2,start,group)
            if end>start:ws.merge_cells(start_row=2,start_column=start,end_row=2,end_column=end)
            start=end+1
        for i,c in enumerate(cols,5):ws.cell(3,i,c['label'])
        def write_values(row,vals):
            for col,v in enumerate(vals,1):
                cell=ws.cell(row,col,v)
                if isinstance(v,str):cell.data_type='s' # Never execute source text as Excel formulas.
        n=4
        for r in data['rows']:
            if r['status']=='cancelled':continue
            write_values(n,[date.fromisoformat(r['registered_on']),r['number'],r['source'],date.fromisoformat(r['document_on']) if r['document_on'] else '']+[Decimal(r['metrics'][c['key']]) if c['key'].endswith('_amount') else r['metrics'][c['key']] for c in cols]);n+=1
        write_values(n,['Итого','','','']+[Decimal(data['totals'][c['key']]) if c['key'].endswith('_amount') else data['totals'][c['key']] for c in cols])
        for row in ws:
            for cell in row:
                cell.alignment=Alignment(wrap_text=True,vertical='center')
                cell.border=Border(bottom=Side(style='thin',color='DCE3EC'))
                if cell.row<=3 or cell.row==n:cell.font=Font(bold=True);cell.fill=PatternFill('solid',fgColor='E8EEF8')
                if isinstance(cell.value,date):cell.number_format='DD.MM.YYYY'
                if cell.column>=5 and cols[cell.column-5]['key'].endswith('_amount'):cell.number_format='#,##0.00'
        for c in range(1,width+1):ws.column_dimensions[get_column_letter(c)].width=15 if c!=3 else 28
        ws.row_dimensions[2].height=60;ws.row_dimensions[3].height=100
        ws.freeze_panes='E4';ws.print_title_rows='1:3';ws.sheet_properties.pageSetUpPr.fitToPage=True
        ws.page_setup.orientation='landscape';ws.page_setup.paperSize=ws.PAPERSIZE_A3;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
        ws.print_area=f'A1:{get_column_letter(width)}{n}'
        notes=w.create_sheet('Правила');notes.append(['Сумма наименований — сумма показателей по партиям, не уникальный фонд.'])
        notes.append(['Отменённые поступления исключены. Списания не уменьшают исторические поступления.'])
        notes.append(['Суммы в KZT, доставка не включена. Все поступления приняты на баланс.'])
        notes.append(['Отчёт рассчитан по текущим данным каталога и поступлений. Пустая дата документа означает, что она не указана в поступлении.'])
        buffer=BytesIO();w.save(buffer)
        return Response(buffer.getvalue(),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename="ksu-{year}.xlsx"'})
    return router
