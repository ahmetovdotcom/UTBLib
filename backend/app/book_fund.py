"""Current stock, counted once per physical copy; no accounting writes."""
import re
from datetime import datetime, timezone
from sqlalchemy import func, or_, select
from .db import Acquisition, AcquisitionLine, Copy, Record
from .ksu_auto import DEFAULT_RULES, norm, vals

CATEGORIES = [
    ('study', 'Учебная'),
    ('methodical', 'Учебно-методическая'),
    ('science', 'Научная'),
    ('reference', 'Справочная'),
    ('fiction', 'Художественная'),
    ('other', 'Прочая / вид не определён'),
]
LANGUAGES = ('kaz', 'rus', 'foreign', 'multilingual', 'unknown')
CODE_RULES = {norm(code): rule for code, rule in DEFAULT_RULES.items()}


def label_key(value):
    return re.sub(r'[\s\-–—]+', ' ', value.strip().casefold().replace('ё', 'е'))


LABEL_KINDS = {}
for kind, labels in {
    'study': ['Учебная', 'Учебная литература', 'Учебник', 'Учебное пособие', 'Учебно-практическое пособие',
              'Оқулық', 'Оқу құралы', 'Оқу-практикалық құрал', 'Дәрістер жинағы'],
    'methodical': ['Учебно-методическая', 'Учебно-методическая литература', 'Учебно-методическое пособие',
                   'Учебно-методического пособия', 'Учебно-методический курс', 'Методическое пособие',
                   'Методические указания', 'Методические рекомендации', 'Практикум', 'Учебный практикум',
                   'Лабораторный практикум', 'Рабочая тетрадь', 'Оқу әдістемелік құрал',
                   'Оқу әдістемелік құралы', 'Оку әдістемелік құрал', 'Әдістемелік нұсқаулық'],
    'science': ['Научная', 'Научная литература', 'Монография', 'Ғылыми әдебиет'],
    'reference': ['Справочная', 'Справочная литература', 'Справочник', 'Словарь', 'Энциклопедия',
                  'Терминологический словарь', 'Анықтамалық', 'Анықтамалық сөздік', 'Сөздік'],
    'fiction': ['Художественная', 'Художественная литература', 'Көркем әдебиет', 'Роман', 'Роман-эпопея'],
}.items():
    LABEL_KINDS.update({label_key(label): kind for label in labels})


def code_kind(code):
    if re.fullmatch(r'КУМ[КРИ]', code) or code.startswith('МИ/'):
        return 'methodical'
    if re.fullmatch(r'К[УНСХ][КРИ]', code):
        return {'У': 'study', 'Н': 'science', 'С': 'reference', 'Х': 'fiction'}[code[1]]
    return None


def is_non_book(code):
    return code.startswith(('CD/', 'АУД/', 'ВИД/')) or code in ('ДКИ', 'ДКК', 'ДКР')


def language(marc, coded_languages):
    """Conflicting sources are unknown; multilingual copies get a single column."""
    raw = vals(marc, '041', 'a')
    codes = set()
    aliases = {'kk': 'kaz', 'ru': 'rus', 'en': 'eng', 'қазақша': 'kaz',
               'казахский': 'kaz', 'русский': 'rus', 'английский': 'eng'}
    for value in raw:
        value = aliases.get(value.casefold(), value.casefold())
        for part in re.split(r'[\s;,/|+]+', value):
            if part:
                # MARC also permits concatenated three-letter language codes.
                if not re.fullmatch(r'(?:[a-z]{3})+', part):
                    return 'unknown'
                codes.update(part[i:i+3] for i in range(0, len(part), 3))
    if codes & {'und', 'zxx', 'unk'}:
        return 'unknown'
    if 'mul' in codes:
        return 'multilingual'
    groups = {c if c in ('kaz', 'rus') else 'foreign' for c in codes}
    if len(codes) > 1:
        return 'multilingual'
    if len(groups | coded_languages) > 1:
        return 'unknown'
    return next(iter(groups | coded_languages), 'unknown')


def classify(marc):
    codes = {norm(c) for c in vals(marc, '952', 'a')}
    # Exclude only unambiguous audiovisual/electronic material. Mixed or missing
    # classifications remain visible in stock, never silently disappear.
    non_book = bool(codes) and all(is_non_book(c) for c in codes)
    kinds = {code_kind(c) for c in codes} - {None}
    labels = {LABEL_KINDS.get(label_key(v)) for v in vals(marc, '952', 'c')} - {None}
    if len(kinds) == 1 and all(code_kind(c) and c in CODE_RULES for c in codes):
        kind = next(iter(kinds))
        # The generic КУ code includes manuals; an explicit methodical label
        # provides the finer split required by this report.
        if kind == 'study' and labels == {'methodical'}:
            kind = 'methodical'
    elif not codes and len(labels) == 1:
        kind = next(iter(labels))
    else:
        kind = 'other'
    coded_languages = {CODE_RULES[c]['language'] for c in codes if c in CODE_RULES} - {''}
    return kind, language(marc, coded_languages), non_book


def empty_counts():
    return dict(total=0, **{key: 0 for key in LANGUAGES})


def report(s):
    # Aggregate first: one MARC document is loaded per record, not per copy.
    record_id = func.coalesce(Copy.record_id, AcquisitionLine.record_id)
    stock = (select(record_id.label('record_id'), func.count(Copy.id).label('quantity'))
             .select_from(Copy)
             .outerjoin(AcquisitionLine, Copy.line_id == AcquisitionLine.id)
             .outerjoin(Acquisition, AcquisitionLine.acquisition_id == Acquisition.id)
             .where(Copy.status == 'active', or_(Copy.line_id.is_(None), Acquisition.status == 'posted'))
             .group_by(record_id).subquery())
    rows = {key: dict(key=key, label=label, **empty_counts()) for key, label in CATEGORIES}
    totals = empty_counts()
    excluded = records = needs_review = 0
    query = select(Record.marc, stock.c.quantity).select_from(stock).outerjoin(Record, Record.id == stock.c.record_id)
    for marc, quantity in s.execute(query):
        kind, lang, non_book = classify(marc or {})
        if non_book:
            excluded += quantity
            continue
        records += 1
        rows[kind]['total'] += quantity
        rows[kind][lang] += quantity
        totals['total'] += quantity
        totals[lang] += quantity
        if kind == 'other' or lang == 'unknown':
            needs_review += quantity
    return {
        'as_of': datetime.now(timezone.utc).isoformat(),
        'rows': list(rows.values()), 'totals': totals, 'records': records,
        'excluded_non_book': excluded, 'needs_review': needs_review,
    }
