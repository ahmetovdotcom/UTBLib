"""Read-only loan statistics. Each Loan is one issue, independent of renewals/events."""
import csv
import io
import re
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import String, cast, func, select
from .db import AcquisitionLine, Copy, DocumentType, Record
from .circulation_models import Loan
from .reader_models import Branch, Reader
from .reader_core import CATEGORIES as READER_CATEGORIES, TZ, local_bounds
from .book_fund import CATEGORIES, classify
from .ksu_auto import vals
from .gost import describe

DIMENSIONS = {
    'record': 'Библиографическая запись', 'kind': 'Категория литературы',
    'literature_type': 'Вид литературы', 'specialty': 'Специальность',
    'discipline': 'Дисциплина', 'language': 'Язык', 'document_type': 'Тип документа',
    'branch_id': 'Пункт выдачи (абонемент)', 'category': 'Категория читателя',
}
LIST_FILTERS = tuple(key for key in DIMENSIONS if key != 'record')
LANGUAGES = {'kaz': 'Казахский', 'rus': 'Русский', 'eng': 'Английский', 'ger': 'Немецкий',
             'fre': 'Французский', 'chi': 'Китайский', 'tur': 'Турецкий', 'ara': 'Арабский',
             'mul': 'Несколько языков', 'foreign': 'Иностранный (не уточнён)'}
RULES = ('Период определяется датой выдачи по времени Алматы. Одна выдача — один экземпляр, '
         'выданный читателю; продления не считаются новыми выдачами. Возвращённые и утраченные '
         'книги остаются в истории выдач. Читатели, экземпляры и записи в итогах считаются без повторов. '
         'Одинаковые названия разных библиографических записей не объединяются. '
         'Специальности, дисциплины, языки и виды берутся из текущих карточек книг. '
         'При нескольких значениях выдача учитывается в каждой подходящей группе один раз: '
         'сумма строк и число читателей по группам могут превышать общий итог. '
         'Пункт выдачи сохраняется при оформлении и не меняется при перемещении экземпляра. '
         'В старых выдачах указан ранее сохранённый пункт; если его нет — «Не указано». '
         'История выдач из старой программы MARCSQL в этот отчёт не входит.')


class Filters(BaseModel):
    model_config = ConfigDict(extra='forbid')
    date_from: date = Field(default_factory=lambda: datetime.now(TZ).date().replace(day=1))
    date_to: date = Field(default_factory=lambda: datetime.now(TZ).date())
    group_by: Literal['record', 'kind', 'literature_type', 'specialty', 'discipline', 'language',
                      'document_type', 'branch_id', 'category'] = 'record'
    q: str = Field(default='', max_length=200)
    record_id: int | None = Field(default=None, ge=1)
    kind: list[str] = Field(default_factory=list, max_length=30)
    literature_type: list[str] = Field(default_factory=list, max_length=100)
    specialty: list[str] = Field(default_factory=list, max_length=100)
    discipline: list[str] = Field(default_factory=list, max_length=100)
    language: list[str] = Field(default_factory=list, max_length=100)
    document_type: list[str] = Field(default_factory=list, max_length=100)
    branch_id: list[str] = Field(default_factory=list, max_length=100)
    category: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode='after')
    def validate_filters(self):
        if not date(1900, 1, 1) <= self.date_from <= self.date_to <= date(2200, 12, 31):
            raise ValueError('Укажите корректный период с 1900 по 2200 год')
        if (self.date_to - self.date_from).days >= 3660:
            raise ValueError('Максимальный период одного отчёта — 3660 дней')
        if any(len(v) > 1000 for key in LIST_FILTERS for v in getattr(self, key)):
            raise ValueError('Слишком длинное значение фильтра')
        if any(v not in dict(CATEGORIES) for v in self.kind):
            raise ValueError('Неизвестная категория литературы')
        if any(v and (not v.isdecimal() or int(v) < 1) for v in self.document_type + self.branch_id):
            raise ValueError('Некорректный идентификатор фильтра')
        self.q = self.q.strip()
        return self


def parse_filters(request: Request):
    if set(request.query_params) - set(Filters.model_fields) - {'format'}:
        raise HTTPException(422, 'Неизвестный параметр отчёта')
    values = {key: request.query_params.getlist(key) if key in LIST_FILTERS else request.query_params[key]
              for key in Filters.model_fields if key in request.query_params}
    try:
        return Filters.model_validate(values)
    except ValidationError as error:
        raise HTTPException(422, '; '.join(e['msg'].removeprefix('Value error, ') for e in error.errors())) from None


def languages(marc):
    raw = vals(marc, '041', 'a')
    if not raw:
        coded = next((f.get('value', '')[35:38].strip() for f in marc.get('fields', [])
                      if f.get('tag') == '008' and len(f.get('value', '')) >= 38), '')
        if coded and coded != '|||': raw = [coded]
    aliases = {'kk': 'kaz', 'ru': 'rus', 'en': 'eng', 'deu': 'ger', 'fra': 'fre', 'zho': 'chi',
               'казахский': 'kaz', 'қазақша': 'kaz', 'русский': 'rus', 'английский': 'eng'}
    result = set()
    for value in raw:
        for part in re.split(r'[\s;,/|+]+', value.strip().casefold()):
            part = aliases.get(part, part)
            if re.fullmatch(r'(?:[a-z]{3})+', part):
                result.update(aliases.get(part[i:i+3], part[i:i+3]) for i in range(0, len(part), 3))
            elif part: result.add(part)
    result -= {'und', 'unk', 'zxx'}
    if not result and not raw:
        fallback = classify(marc)[1]
        if fallback in ('kaz', 'rus', 'foreign'): result.add(fallback)
        if fallback == 'multilingual': result.add('mul')
    return sorted(result) or ['']


def metadata(record):
    marc = record.marc
    title = ' '.join(vals(marc, '245', 'a')) or 'Без заглавия'
    author = '; '.join(vals(marc, '100', 'a'))
    leader = marc.get('leader', '')
    kind = 'component' if len(leader) > 7 and leader[7] in ('a', 'b') else 'single'
    return {'id': record.id, 'label': title, 'author': author,
            'description': describe(marc, kind)['text'],
            'isbn': '; '.join(vals(marc, '020', 'a')),
            'kind': [classify(marc)[0]], 'document_type': [str(record.type_id)],
            'literature_type': sorted(set(vals(marc, '952', 'c'))) or [''],
            'specialty': sorted(set(vals(marc, '952', 'j'))) or [''],
            'discipline': sorted(set(vals(marc, '952', 'i'))) or [''],
            'language': languages(marc)}


def loan_query():
    record_id = func.coalesce(Copy.record_id, AcquisitionLine.record_id)
    return (select(Loan.reader_id, Loan.copy_id, record_id.label('record_id'),
                   Loan.issued_at, Loan.branch_id, Reader.category)
            .join(Copy, Loan.copy_id == Copy.id)
            .outerjoin(AcquisitionLine, Copy.line_id == AcquisitionLine.id)
            .join(Reader, Loan.reader_id == Reader.id))


def labels(s):
    return {'kind': dict(CATEGORIES), 'language': LANGUAGES, 'category': READER_CATEGORIES,
            'document_type': {str(t.id): t.name for t in s.scalars(select(DocumentType))},
            'branch_id': {str(b.id): b.name for b in s.scalars(select(Branch))}}


def options(s):
    names = labels(s)
    choices = {key: set() for key in LIST_FILTERS}
    source = loan_query().subquery()
    for r in s.scalars(select(Record).where(Record.id.in_(select(source.c.record_id)))):
        info = metadata(r)
        for key in LIST_FILTERS:
            if key in info: choices[key].update(info[key])
    for branch, category in s.execute(select(Loan.branch_id, Reader.category).join(Reader, Reader.id == Loan.reader_id).distinct()):
        choices['branch_id'].add(str(branch) if branch is not None else '')
        choices['category'].add(category or '')
    return {'dimensions': DIMENSIONS, 'filters': {key: sorted(
        [{'value': v, 'label': names.get(key, {}).get(v, v) or 'Не указано'} for v in values],
        key=lambda o: o['label'].casefold()) for key, values in choices.items()}}


def empty():
    return {'loans': 0, 'readers': set(), 'copies': set(), 'records': set()}


def add(counts, row):
    counts['loans'] += 1
    counts['readers'].add(row.reader_id)
    counts['copies'].add(row.copy_id)
    counts['records'].add(row.record_id)


def counts(value):
    return {key: len(v) if isinstance(v, set) else v for key, v in value.items()}


def report(s, f):
    query = loan_query().where(Loan.issued_at >= local_bounds(f.date_from)[0],
                               Loan.issued_at < local_bounds(f.date_to)[1])
    if f.branch_id:
        query = query.where(func.coalesce(cast(Loan.branch_id, String), '').in_(f.branch_id))
    if f.category: query = query.where(Reader.category.in_(f.category))
    source = query.subquery()
    record_query = select(Record).where(Record.id.in_(select(source.c.record_id)))
    if f.record_id: record_query = record_query.where(Record.id == f.record_id)
    info = {}
    for r in s.scalars(record_query):
        m = metadata(r)
        if any(getattr(f, k) and not set(getattr(f, k)).intersection(m[k])
               for k in LIST_FILTERS if k in m): continue
        if f.q and f.q.casefold() not in ' '.join([m['label'], m['author'], m['isbn'], str(r.id)]).casefold(): continue
        info[r.id] = m
    totals = empty(); groups = {}; trend = {}
    names = labels(s)
    # Above 3 months show months; shorter periods show every day, including zero days.
    monthly = (f.date_to - f.date_from).days > 92
    current = f.date_from
    while current <= f.date_to:
        key = current.isoformat()[:7] if monthly else current.isoformat()
        trend.setdefault(key, empty())
        current += timedelta(days=1)
    for row in s.execute(query.execution_options(yield_per=1000)):
        m = info.get(row.record_id)
        if m is None: continue
        add(totals, row)
        stamp = row.issued_at
        if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
        day = stamp.astimezone(TZ).date().isoformat()
        add(trend[day[:7] if monthly else day], row)
        if f.group_by == 'record': keys = [str(row.record_id)]
        elif f.group_by == 'branch_id': keys = [str(row.branch_id) if row.branch_id is not None else '']
        elif f.group_by == 'category': keys = [row.category or '']
        else: keys = m[f.group_by]
        for key in keys:
            if key not in groups:
                details = ({'record_id': m['id'], 'label': m['label'], 'author': m['author'],
                            'description': m['description'], 'isbn': m['isbn']} if f.group_by == 'record'
                           else {'label': names.get(f.group_by, {}).get(key, key) or 'Не указано'})
                groups[key] = {'key': key, **details, **empty()}
            add(groups[key], row)
    rows = sorted((counts(v) for v in groups.values()), key=lambda r: (-r['loans'], r['label'].casefold(), r['key']))
    return {'filters': f.model_dump(mode='json'), 'timezone': str(TZ), 'rules': RULES,
            'totals': counts(totals), 'rows': rows, 'dimension': DIMENSIONS[f.group_by],
            'trend_unit': 'month' if monthly else 'day',
            'trend': [{'period': k, **counts(v)} for k, v in trend.items()]}


def export_report(data, f, format, filter_options):
    from .readers import safe_cell
    table = [['Статистика книговыдачи'], [f'{f.date_from} — {f.date_to} · {TZ}'],
             [data['dimension'], 'ID записи', 'Библиографическое описание', 'Выдач', 'Читателей', 'Экземпляров', 'Записей']]
    for row in data['rows']:
        table.append([row['label'], row.get('record_id', ''), row.get('description', ''),
                      row['loans'], row['readers'], row['copies'], row['records']])
    t = data['totals']; table.append(['Итого без повторов', '', '', t['loans'], t['readers'], t['copies'], t['records']])
    table.extend([[], [RULES], [], ['Применённые фильтры']])
    for key, value in f.model_dump(mode='json').items():
        if key in ('date_from', 'date_to', 'group_by') or value is None or value == '' or value == []: continue
        name = {str(o['value']): o['label'] for o in filter_options.get(key, [])}
        text = ', '.join(name.get(str(v), str(v)) or 'Не указано' for v in value) if isinstance(value, list) else value
        table.append([DIMENSIONS.get(key, {'q': 'Поиск', 'record_id': 'ID записи'}.get(key, key)), text])
    table.extend([[], ['Динамика', 'Выдач', 'Читателей']])
    table.extend([[r['period'], r['loans'], r['readers']] for r in data['trend']])
    headers = {'Content-Disposition': f'attachment; filename="loans-{f.date_from}-{f.date_to}.{format}"'}
    if format == 'csv':
        out = io.StringIO(); csv.writer(out, delimiter=';').writerows([[safe_cell(v) for v in row] for row in table])
        return Response('\ufeff' + out.getvalue(), media_type='text/csv; charset=utf-8', headers=headers)
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook(); ws = wb.active; ws.title = 'Книговыдача'
    for row in table: ws.append([safe_cell(v) if isinstance(v, str) else v for v in row])
    for row in ws:
        for cell in row: cell.alignment = Alignment(vertical='top', wrap_text=True)
        if row[0].row == 3 or str(row[0].value).startswith('Итого'):
            for cell in row: cell.font = Font(bold=True); cell.fill = PatternFill('solid', fgColor='E4EEF5')
    for key, width in {'A': 45, 'B': 13, 'C': 70, 'D': 14, 'E': 14, 'F': 14, 'G': 14}.items(): ws.column_dimensions[key].width = width
    ws.freeze_panes = 'D4'; ws.print_title_rows = '1:3'
    ws.page_setup.orientation = 'landscape'; ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr.fitToPage = True; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    out = io.BytesIO(); wb.save(out)
    return Response(out.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers=headers)


def make_router(auth, db):
    router = APIRouter(prefix='/api/statistics/circulation', dependencies=[Depends(auth)])

    @router.get('/options')
    def get_options(s=Depends(db)):
        return options(s)

    @router.get('')
    def get_report(f=Depends(parse_filters), s=Depends(db)):
        return report(s, f)

    @router.get('/export')
    def export(format: Literal['xlsx', 'csv'] = 'xlsx', f=Depends(parse_filters), s=Depends(db)):
        return export_report(report(s, f), f, format, options(s)['filters'])

    return router
