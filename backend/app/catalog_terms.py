"""Browse values actually used in catalogue records, with per-record counts."""
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text

from .catalog_attention import field_options
from .catalog_search import parse_conditions, sqlite_lower
from .db import DocumentType

SPACES = ' \t\n\r\u00a0'


def prepare(session, type_id):
    postgres = session.bind.dialect.name == 'postgresql'
    if not postgres:
        sqlite_lower(session)
    types = list(session.scalars(select(DocumentType).order_by(DocumentType.id)))
    if type_id is not None:
        types = [t for t in types if t.id == type_id]
        if not types:
            raise HTTPException(404, 'Тип документа не найден')
    return postgres, types


def value_rows(postgres, field=None):
    """Only internal SQL fragments are interpolated; field/code/type are bound."""
    scope = 'SELECT id, marc FROM records WHERE (CAST(:type_id AS INTEGER) IS NULL OR type_id = :type_id)'
    if postgres:
        fields = "base, jsonb_array_elements(base.marc->'fields') f"
        subs = fields + ", jsonb_array_elements(COALESCE(NULLIF(f->'subfields','null'::jsonb),'[]'::jsonb)) sf"
        tag, code, fv, sv, leader = "f->>'tag'", "sf->>'code'", "f->>'value'", "sf->>'value'", "marc->>'leader'"
    else:
        fields = "base, json_each(json_extract(base.marc,'$.fields')) f"
        subs = fields + ", json_each(json_extract(f.value,'$.subfields')) sf"
        tag, code = "json_extract(f.value,'$.tag')", "json_extract(sf.value,'$.code')"
        fv, sv, leader = "json_extract(f.value,'$.value')", "json_extract(sf.value,'$.value')", "json_extract(marc,'$.leader')"
    params = {}
    if field is None:
        rows = (f"SELECT base.id, '000' AS key, {leader} AS value FROM base UNION ALL "
                f"SELECT base.id, {tag} AS key, {fv} AS value FROM {fields} WHERE {tag} < '010' UNION ALL "
                f"SELECT base.id, ({tag}) || '$' || ({code}) AS key, {sv} AS value FROM {subs} WHERE {tag} >= '010'")
    else:
        t, _, c = field.partition('$')
        params['tag'] = t
        if t == '000':
            rows = f"SELECT id, {leader} AS value FROM base"
            params.clear()
        elif int(t) < 10:
            rows = f"SELECT base.id, {fv} AS value FROM {fields} WHERE {tag} = :tag"
        else:
            rows = f"SELECT base.id, {sv} AS value FROM {subs} WHERE {tag} = :tag"
            if c:
                rows += f" AND {code} = :code"
                params['code'] = c
    return f'WITH base AS ({scope}), raw_values AS ({rows})', params


def make_router(auth, db, official, local):
    router = APIRouter(prefix='/api/catalog-search', dependencies=[Depends(auth)])

    @router.get('/options')
    def options(type_id: int | None = None, s=Depends(db)):
        pg, types = prepare(s, type_id)
        cte, params = value_rows(pg)
        trim = 'btrim' if pg else 'trim'
        # Count each record once, also for whole-field options (e.g. any 245 subfield).
        tag = "split_part(key,'$',1)" if pg else "substr(key,1,3)"
        sql = (cte + f", filled AS (SELECT id,key FROM raw_values WHERE {trim}(value,:spaces) <> ''), "
               f"keys AS (SELECT id,key FROM filled UNION SELECT id,{tag} AS key FROM filled) "
               "SELECT key,count(DISTINCT id) AS count FROM keys GROUP BY key")
        counts = dict(s.execute(text(sql), {**params, 'type_id': type_id, 'spaces': SPACES}).all())
        configured = {c['tag'] for t in types for c in t.config}
        configured |= {f"{c['tag']}${code}" for t in types for c in t.config for code in c.get('subfields', [])}
        fields = field_options(types, official, local)
        for f in fields:
            f['configured'] = f['key'] in configured
            f['count'] = counts.get(f['key'], 0)
        return {'fields': fields}

    @router.get('/values')
    def values(field: str, type_id: int | None = None, q: str = Query('', max_length=300),
               offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), s=Depends(db)):
        parse_conditions(json.dumps([{'field': field, 'value': 'validate'}]), official, local)
        pg, _ = prepare(s, type_id)
        cte, params = value_rows(pg, field)
        lower, trim = ('lower', 'btrim') if pg else ('catalog_lower', 'trim')
        value = f'{trim}(value,:spaces)'
        pattern = q.strip().lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        params.update(type_id=type_id, spaces=SPACES, query='%' + pattern + '%')
        grouped = (cte + f", terms AS (SELECT min({value}) AS value,count(DISTINCT id) AS count "
                   f"FROM raw_values WHERE {value} <> '' AND {lower}({value}) LIKE :query ESCAPE '\\' "
                   f"GROUP BY {lower}({value})) ")
        total = s.scalar(text(grouped + 'SELECT count(*) FROM terms'), params)
        items = s.execute(text(grouped + f'SELECT value,count FROM terms ORDER BY {lower}(value),value LIMIT :limit OFFSET :offset'),
                          {**params, 'limit': limit, 'offset': offset}).mappings().all()
        return {'items': [dict(r) for r in items], 'total': total, 'offset': offset, 'limit': limit}

    return router
