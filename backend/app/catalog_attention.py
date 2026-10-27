"""Read-only catalogue checks against current field and vocabulary settings."""
from collections import defaultdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from .db import DocumentType, Record, VocabularyEntry
from .vocabulary import normalized


def field_options(types, official, local):
    # Include every known field/subfield, including those hidden in a worksheet.
    local_tags = {c['tag'] for t in types for c in t.config if c.get('local')}
    configs = {c['tag']: c for t in types for c in t.config}
    result = []
    for tag in sorted(set(official) | set(local)):
        spec = local.get(tag) if tag in local_tags or tag not in official else official[tag]
        cfg = configs.get(tag, {})
        label = cfg.get('label') or spec['label']
        result.append({'key': tag, 'tag': tag, 'code': None, 'label': label,
                       'local': bool(spec.get('local') or cfg.get('label')), 'parent_label': label,
                       'configured': tag in configs})
        if int(tag) < 10:
            continue
        subs = {s['code']: s for source in (official.get(tag, {}), local.get(tag, {}), spec)
                for s in source.get('subfields', [])}
        for code, sf in sorted(subs.items()):
            is_local = bool(spec.get('local') and any(s['code'] == code for s in spec.get('subfields', [])))
            result.append({'key': f'{tag}${code}', 'tag': tag, 'code': code, 'label': sf['label'],
                           'local': is_local, 'parent_label': label, 'configured': tag in configs})
    return result


def record_values(marc):
    values = defaultdict(list)
    leader = normalized(marc.get('leader') or '')
    if leader:
        values['000'].append(leader)
    for field in marc.get('fields', []):
        tag = field['tag']
        value = normalized(field.get('value') or '')
        if value:
            values[tag].append(value)
        for sf in field.get('subfields') or []:
            value = normalized(sf.get('value') or '')
            if value:
                values[tag].append(value)
                values[f"{tag}${sf['code']}"].append(value)
    return values


def vocabulary_rules(types, selected):
    rules = defaultdict(dict)
    for t in types:
        for field in t.config:
            tag = field['tag']
            for code, settings in field.get('vocabularies', {}).items():
                key = tag if code == '_' else f'{tag}${code}'
                # Operator names are suggestions and may include former employees.
                if (tag, code) == ('097', 'b') or settings.get('auto_add'):
                    continue
                if tag in selected or key in selected:
                    rules[t.id][key] = {'tag': tag, 'code': code, 'allow_edit': bool(settings.get('allow_edit'))}
    return rules


def inspect_record(values, selected, checks, rules, known):
    issues = []
    if 'missing' in checks:
        for key in selected:
            # A tag checks the entire field; a subfield checks only its own values.
            if not values.get(key):
                issues.append({'field': key, 'kind': 'missing', 'values': [], 'allow_edit': False})
    if 'vocabulary' in checks:
        for key, rule in rules.items():
            invalid = sorted(set(values.get(key, [])) - known.get(key, set()))
            if invalid:
                issues.append({'field': key, 'kind': 'vocabulary', 'values': invalid,
                               'allow_edit': rule['allow_edit']})
    return issues


def make_router(auth, db, official, local):
    router = APIRouter(prefix='/api/catalog-attention', dependencies=[Depends(auth)])

    def load_types(s, type_id):
        stmt = select(DocumentType).order_by(DocumentType.id)
        if type_id is not None:
            stmt = stmt.where(DocumentType.id == type_id)
        types = list(s.scalars(stmt))
        if type_id is not None and not types:
            raise HTTPException(404, 'Тип документа не найден')
        return types

    @router.get('/options')
    def options(type_id: int | None = None, s=Depends(db)):
        return {'fields': field_options(load_types(s, type_id), official, local)}

    @router.get('')
    def report(
        fields: Annotated[list[str], Query(min_length=1, max_length=100)],
        checks: Annotated[list[Literal['missing', 'vocabulary']], Query(min_length=1, max_length=2)] = ['missing', 'vocabulary'],
        type_id: int | None = None,
        q: str = Query('', max_length=200),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        s=Depends(db),
    ):
        types = load_types(s, type_id)
        available = {f['key'] for f in field_options(types, official, local)}
        selected = sorted(set(fields))
        if any(key not in available for key in selected):
            raise HTTPException(422, 'Выберите поля из списка доступных полей')
        rules = vocabulary_rules(types, selected)
        known = defaultdict(lambda: defaultdict(set))
        # Load dictionaries once, never add values or change records while checking.
        relevant_types = list(rules)
        if relevant_types and 'vocabulary' in checks:
            for entry in s.scalars(select(VocabularyEntry).where(VocabularyEntry.type_id.in_(relevant_types))):
                key = entry.tag if entry.code == '_' else f'{entry.tag}${entry.code}'
                if key in rules[entry.type_id]:
                    known[entry.type_id][key].add(normalized(entry.value))
        stmt = select(Record.id, Record.type_id, Record.marc).order_by(Record.id.desc())
        if type_id is not None:
            stmt = stmt.where(Record.type_id == type_id)
        if q.strip():
            stmt = stmt.where(Record.search_text.contains(q.strip().casefold(), autoescape=True))
        items = []
        total = scanned = missing = vocabulary = 0
        # Bound memory use; filter BEFORE pagination and count each record once.
        for record_id, record_type, marc in s.execute(stmt.execution_options(yield_per=250)):
            scanned += 1
            values = record_values(marc)
            issues = inspect_record(values, selected, checks, rules.get(record_type, {}), known.get(record_type, {}))
            if not issues:
                continue
            total += 1
            kinds = {i['kind'] for i in issues}
            missing += 'missing' in kinds
            vocabulary += 'vocabulary' in kinds
            if offset < total <= offset + limit:
                items.append({'id': record_id, 'type_id': record_type,
                              'title': ' '.join(values.get('245$a', [])) or 'Без заглавия',
                              'author': '; '.join(values.get('100$a', [])),
                              'udc': '; '.join(values.get('080$a', [])), 'issues': issues})
        return {'items': items, 'total': total, 'scanned': scanned, 'offset': offset, 'limit': limit,
                'counts': {'missing': missing, 'vocabulary': vocabulary}}

    return router
