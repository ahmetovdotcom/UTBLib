"""Read-only, explicitly whitelisted catalogue contract for the existing library site.

Never serialize Record/Copy models or search Record.search_text here: those include
staff notes, acquisition data and other fields that are not public bibliography.
"""
import re
from collections import Counter
from datetime import date
from threading import RLock
from weakref import WeakKeyDictionary

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, select

from .db import AcquisitionLine, Copy, DocumentType, Record, get_db
from .circulation_models import ACTIVE_RESERVATIONS, CopyCirculation, Loan, Reservation
from .reader_models import Branch

router = APIRouter(prefix='/api/public/v1', tags=['Public catalogue'])
PUBLIC_PATHS = frozenset(('/api/public/v1/catalog', '/api/public/v1/facets', '/api/public/v1/books/{identifier}'))
_cache = WeakKeyDictionary()
_lock = RLock()


def values(marc, tag, code):
    return [str(sf.get('value', '')).strip() for f in marc.get('fields', [])
            if f.get('tag') == tag for sf in (f.get('subfields') or [])
            if sf.get('code') == code and str(sf.get('value', '')).strip()]


def language(value):
    return {'ru': 'ru', 'rus': 'ru', 'kk': 'kk', 'kaz': 'kk', 'kz': 'kk', 'en': 'en', 'eng': 'en'}.get(value.strip().casefold(), 'other')


def isbn_key(value):
    return re.sub(r'[^0-9X]', '', value.upper())


def project(record, types):
    m = record.marc
    v = lambda tag, code: values(m, tag, code)
    f = lambda tag, code: ' · '.join(v(tag, code))
    year = re.search(r'\b(1[4-9]\d{2}|20\d{2})\b', f('260', 'c') or f('264', 'c'))
    title = f('245', 'a') or 'Без заглавия'
    authors = list(dict.fromkeys(v('100', 'a') + v('700', 'a')))
    langs = list(dict.fromkeys(language(x) for x in v('041', 'a')))
    if not langs:
        fixed = next((str(x.get('value') or '') for x in m.get('fields', []) if x.get('tag') == '008'), '')
        if len(fixed) >= 38 and re.fullmatch('[a-z]{3}', fixed[35:38]):
            langs = [language(fixed[35:38])]
    if not langs:
        langs = ['other']
    kind = types.get(record.type_id, '').casefold()
    level = str(m.get('leader', ''))[7:8]
    resource = 'article' if 'стать' in kind or level == 'a' else 'journal' if 'журнал' in kind or 'период' in kind or level == 's' else 'book'
    category = f('952', 'c') or f('952', 'a')
    b = {
        'id': f'utblib-{record.id}', 'source': 'utblib',
        'title': {'display': title, 'raw': title, 'subtitle': f('245', 'b'), 'original': title, 'isFallback': False},
        'primaryAuthor': f('100', 'a'), 'authors': [{'name': x} for x in authors],
        'contributors': [{'name': x, 'role': 'author', 'kind': 'person'} for x in authors],
        'publisher': {'name': f('260', 'b') or f('264', 'b')},
        'publicationPlace': f('260', 'a') or f('264', 'a'),
        'publicationYear': int(year[0]) if year else None,
        'statementOfResponsibility': f('245', 'c'), 'editionStatement': f('250', 'a'),
        'language': {'code': langs[0] if langs else '', 'raw': langs[0] if langs else '', 'label': ''},
        'isbn': {'raw': next(iter(v('020', 'a')), '')}, 'issn': {'raw': f('022', 'a')},
        'resourceType': resource, 'annotation': f('520', 'a'), 'originalAnnotation': f('520', 'a'),
        'keywords': v('653', 'a'), 'metadataLocale': langs[0] if langs else '',
        'subjects': [{'term': x, 'scheme': 'topical'} for x in v('650', 'a')],
        'classification': [{'id': x, 'label': x, 'sourceKind': 'subject', 'scheme': 'topical'} for x in v('650', 'a')],
        'udc': {'raw': f('080', 'a'), 'display': f('080', 'a'), 'description': '', 'source': 'udc' if v('080', 'a') else ''},
        'authorMark': f('090', 'x'), 'physicalExtent': f('300', 'a'), 'physicalDetails': f('300', 'b'),
        'dimensions': f('300', 'c'), 'accompanyingMaterial': f('300', 'e'),
        'seriesTitle': f('490', 'a') or f('440', 'a'), 'seriesNumber': f('490', 'v'),
        'partNumber': f('245', 'n'), 'partTitle': f('245', 'p'),
        'ksuLiteratureType': f('952', 'a'), 'faculty': f('952', 'd'),
        'department': f('952', 'e'), 'disciplines': f('952', 'i'), 'specialty': f('952', 'j'),
        # URLs, notes and attachments are not public until a publication policy exists.
        'coverPath': None, 'electronicMaterials': [], 'relatedMaterials': [], 'similarMaterials': [],
        'viewer': {'authenticated': False, 'canReserve': False, 'reservationEligible': False, 'activeLoan': None},
        '_id': record.id, '_languages': langs, '_isbns': [isbn_key(x) for x in v('020', 'a')], '_category': category,
    }
    b['_search'] = ' '.join([title, f('245', 'b'), *authors, b['publisher']['name'], *v('020', 'a'),
                           *b['_isbns'], f('080', 'a'), f('520', 'a'), *v('653', 'a'), *v('650', 'a')]).casefold()
    return b


def metadata(s):
    """Cache only public projections; refresh changed records by their existing version."""
    engine = s.get_bind()
    with _lock:
        types = dict(s.execute(select(DocumentType.id, DocumentType.name)).all())
        versions = dict(s.execute(select(Record.id, Record.version)).all())
        old_types, old_versions, books = _cache.get(engine, ({}, {}, {}))
        changed = [rid for rid, version in versions.items() if old_versions.get(rid) != version or old_types != types]
        books = {rid: book for rid, book in books.items() if rid in versions}
        for start in range(0, len(changed), 500):
            for record in s.scalars(select(Record).where(Record.id.in_(changed[start:start + 500]))):
                books[record.id] = project(record, types)
        _cache[engine] = (types, versions, books)
        return list(books.values())


def inventory(s):
    """Aggregate live copies without retrieving names, loan dates or copy identifiers."""
    rid = func.coalesce(Copy.record_id, AcquisitionLine.record_id)
    state = func.coalesce(CopyCirculation.operation_state, 'normal')
    condition = func.coalesce(CopyCirculation.condition, 'good')
    access = func.coalesce(CopyCirculation.access, 'free')
    available = and_(Loan.id.is_(None), Reservation.id.is_(None), state == 'normal',
                     ~condition.in_(('severe', 'irreparable', 'lost')), access == 'free')
    count = lambda predicate: func.sum(case((predicate, 1), else_=0))
    rows = s.execute(select(rid, Branch.code, Branch.name, func.count(Copy.id), count(available),
        count(Loan.id.is_not(None)), count(state == 'processing'), count(state == 'repair'),
        count(access == 'reading_room'), count(access == 'limited'), func.sum(func.coalesce(CopyCirculation.issue_count, 0)))
        .select_from(Copy).outerjoin(AcquisitionLine, Copy.line_id == AcquisitionLine.id)
        .outerjoin(CopyCirculation, CopyCirculation.copy_id == Copy.id)
        .outerjoin(Branch, Branch.id == CopyCirculation.branch_id)
        .outerjoin(Loan, and_(Loan.copy_id == Copy.id, Loan.closed_at.is_(None)))
        .outerjoin(Reservation, and_(Reservation.assigned_copy_id == Copy.id, Reservation.status.in_(ACTIVE_RESERVATIONS)))
        .where(Copy.status == 'active').group_by(rid, Branch.code, Branch.name)).all()
    stock = {}
    keys = ('total', 'available', 'issued', 'processing', 'repair', 'reading_room', 'limited', 'issues')
    for rid, code, name, *counts in rows:
        item = stock.setdefault(rid, {**dict.fromkeys(keys, 0), 'locations': []})
        counts = dict(zip(keys, map(int, counts)))
        for key in keys:
            item[key] += counts[key]
        item['locations'].append({
            'institutionUnit': {'code': '', 'name': ''}, 'campus': {'code': '', 'name': ''},
            'servicePoint': {'code': code or '', 'name': name or 'Библиотека'},
            'copies': {**{k: counts[k] for k in ('total', 'available', 'issued')}, 'unavailable': counts['total'] - counts['available']},
        })
    return stock


def indicators(stock):
    status = next((name for key, name in (('available', 'available'), ('processing', 'in_processing'),
                  ('repair', 'under_repair'), ('issued', 'issued'), ('total', 'unavailable')) if stock.get(key)), 'no_holdings')
    return {'availability': status, 'format': 'print' if stock.get('total') else 'metadata_only',
            'copySupply': 'in_stock' if stock.get('available', 0) > 1 else 'last_copy' if stock.get('available') else 'absent',
            'popular': False, 'newArrival': False, 'issueCount': stock.get('issues', 0), 'latestRegistrationDate': None,
            'accessRestriction': 'limited' if stock.get('limited') else 'reading_room' if stock.get('reading_room') else 'free'}


def present(book, stock):
    counts = {k: stock.get(k, 0) for k in ('available', 'issued', 'total')}
    return {**{k: v for k, v in book.items() if not k.startswith('_')}, 'copies': counts, 'indicators': indicators(stock),
            'availability': {'isAvailable': counts['available'] > 0, 'availableCopies': counts['available'],
                             'issuedCopies': counts['issued'], 'totalCopies': counts['total'], 'locations': stock.get('locations', [])}}


class Search(BaseModel):
    q: str = Field('', max_length=255)
    title: str = Field('', max_length=255)
    author: str = Field('', max_length=255)
    publisher: str = Field('', max_length=255)
    isbn: str = Field('', max_length=64)
    subject: str = Field('', max_length=500)
    subject_id: str = Field('', max_length=500)
    udc: str = Field('', max_length=128)
    language: str = Field('', max_length=10)
    page: int = Field(1, ge=1, le=1000000)
    limit: int = Field(24, ge=1, le=100)
    sort: str = Field('popular', pattern='^(popular|newest|oldest|title|author)$')
    year_from: int | None = Field(None, ge=1400, le=2100)
    year_to: int | None = Field(None, ge=1400, le=2100)
    available_only: bool = False
    physical_only: bool = False
    material_type: str = Field('all', pattern='^(all|physical|digital|archive)$')
    resource_type: str = Field('', max_length=255)
    category: str = Field('', max_length=255)
    branch: str = Field('', max_length=255)
    fund: str = Field('', max_length=255)
    institution: str = Field('', max_length=255)
    availability: str = Field('', pattern='^(|available|issued|electronic_only|processing|repair|no_holdings)$')
    format: str = Field('', pattern='^(|print|electronic|hybrid)$')


INSTITUTIONS = {'college_library': ('COLLEGE',), 'economic_library': ('ECONOMICS-DESK',),
                'technology_library': ('TECHNOLOGY-DESK',), 'ktslib': ('SCIENTIFIC-LIBRARY', 'READING-ROOM')}


def search(s, p):
    stock = inventory(s)
    rows = []
    split = lambda value: {x.strip() for x in value.split(',') if x.strip()}
    for b in metadata(s):
        c = stock.get(b['_id'], {})
        if any(t not in b['_search'] for t in p.q.strip().casefold().split()): continue
        if p.title.casefold() not in b['title']['display'].casefold(): continue
        if p.author.casefold() not in ' '.join(x['name'] for x in b['authors']).casefold(): continue
        if p.publisher.casefold() not in b['publisher']['name'].casefold(): continue
        if p.isbn and not any(isbn_key(p.isbn) in x for x in b['_isbns']): continue
        if p.udc.casefold() not in b['udc']['raw'].casefold(): continue
        if p.subject.casefold() not in ' '.join([b['annotation'], *b['keywords'], *(x['term'] for x in b['subjects'])]).casefold(): continue
        if p.subject_id and p.subject_id not in [x['term'] for x in b['subjects']]: continue
        if p.language and language(p.language) not in b['_languages']: continue
        year = b['publicationYear']
        if p.year_from and (year is None or year < p.year_from): continue
        if p.year_to and (year is None or year > p.year_to): continue
        if p.available_only and not c.get('available'): continue
        if (p.physical_only or p.material_type == 'physical' or p.format == 'print') and not c.get('total'): continue
        # Electronic publication, archive collections and fund mappings are not provided by this integration.
        if p.material_type in ('digital', 'archive') or p.format in ('electronic', 'hybrid') or p.fund: continue
        if p.resource_type and b['resourceType'] not in split(p.resource_type): continue
        if p.category and b['_category'] not in split(p.category): continue
        branches = {x['servicePoint']['code'] for x in c.get('locations', [])}
        if p.branch and not branches.intersection(split(p.branch)): continue
        if p.institution and not branches.intersection(INSTITUTIONS.get(p.institution, ())): continue
        if p.availability:
            if p.availability == 'no_holdings' and c.get('total'): continue
            if p.availability != 'no_holdings' and not c.get(p.availability): continue
        rows.append(b)
    if p.sort in ('newest', 'oldest'):
        rows.sort(key=lambda b: (b['publicationYear'] is None, (b['publicationYear'] or 0) * (-1 if p.sort == 'newest' else 1), b['_id']))
    elif p.sort == 'popular':
        rows.sort(key=lambda b: (-stock.get(b['_id'], {}).get('issues', 0), b['title']['display'].casefold(), b['_id']))
    else:
        rows.sort(key=lambda b: ((b['primaryAuthor'] if p.sort == 'author' else b['title']['display']).casefold(), b['_id']))
    offset = (p.page - 1) * p.limit
    pages = max(1, (len(rows) + p.limit - 1) // p.limit)
    return {'data': [present(b, stock.get(b['_id'], {})) for b in rows[offset:offset + p.limit]],
            'meta': {'page': p.page, 'per_page': p.limit, 'total': len(rows), 'total_pages': pages, 'totalPages': pages,
                     'total_copies': sum(stock.get(b['_id'], {}).get('total', 0) for b in rows)}}


@router.get('/catalog')
def catalog(params: Search = Query(), s=Depends(get_db)):
    return search(s, params)


@router.get('/facets')
def facets(s=Depends(get_db)):
    books, stock = metadata(s), inventory(s)
    def count(items):
        return [{'value': k, 'count': n} for k, n in sorted(Counter(items).items()) if k]
    years = [b['publicationYear'] for b in books if b['publicationYear']]
    return {'resource_types': count(b['resourceType'] for b in books),
            'languages': count(x for b in books for x in b['_languages']),
            'categories': count(b['_category'] for b in books), 'funds': [],
            'branches': [{'value': code, 'label': name, 'count': sum(any(l['servicePoint']['code'] == code for l in c['locations']) for c in stock.values())}
                         for code, name in s.execute(select(Branch.code, Branch.name))
                         if any(any(l['servicePoint']['code'] == code for l in c['locations']) for c in stock.values())],
            'udc': count(b['udc']['raw'] for b in books),
            'availability': [{'value': key, 'count': sum(bool(stock.get(b['_id'], {}).get(key)) for b in books)}
                             for key in ('available', 'issued', 'processing', 'repair')] +
                            [{'value': 'no_holdings', 'count': sum(not stock.get(b['_id'], {}).get('total') for b in books)}],
            'formats': [{'value': 'print', 'count': sum(bool(stock.get(b['_id'], {}).get('total')) for b in books)}],
            'years': {'min': min(years, default=date.today().year), 'max': max(years, default=date.today().year)}, 'total': len(books)}


@router.get('/books/{identifier}')
def book(identifier: str, s=Depends(get_db)):
    if len(identifier) > 128:
        raise HTTPException(404, 'Книга не найдена')
    books = metadata(s)
    found = next((b for b in books if b['id'] == identifier), None)
    if found is None and len(isbn_key(identifier)) in (10, 13) and not identifier.startswith('utblib-'):
        found = next((b for b in sorted(books, key=lambda b: b['_id']) if isbn_key(identifier) in b['_isbns']), None)
    if found is None:
        raise HTTPException(404, 'Книга не найдена')
    return {'data': present(found, inventory(s).get(found['_id'], {})), 'success': True}
