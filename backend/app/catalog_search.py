"""Parameterized, field-specific catalogue search, applied before pagination."""
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError, field_validator
from sqlalchemy import and_, or_, text


class SearchCondition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    field: str = Field(pattern=r'^\d{3}(?:\$[a-z0-9])?$')
    operator: Literal['contains', 'equals', 'starts_with'] = 'contains'
    value: str = Field(min_length=1, max_length=20000)

    @field_validator('value')
    @classmethod
    def nonempty(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Укажите значение для поиска')
        return value


class SearchConditions(RootModel):
    root: list[SearchCondition] = Field(max_length=8)


def parse_conditions(raw, official, local):
    if not raw:
        return []
    try:
        conditions = SearchConditions.model_validate_json(raw).root
    except ValidationError:
        raise HTTPException(422, 'Проверьте условия поиска: до 8 условий, поле из списка и непустое значение до 20 000 символов.') from None
    allowed = set(official) | set(local)
    allowed |= {f"{tag}${sf['code']}" for source in (official, local)
                for tag, spec in source.items() if int(tag) >= 10 for sf in spec.get('subfields', [])}
    if any(c.field not in allowed for c in conditions):
        raise HTTPException(422, 'Выберите поле или подполе из списка доступных полей.')
    return conditions


def sqlite_lower(session):
    # Register once per physical SQLite connection, not while another cursor is
    # using the function (e.g. concurrent options/values requests in local tests).
    connection = session.connection()
    if not connection.info.get('catalog_lower_ready'):
        connection.connection.driver_connection.create_function(
            'catalog_lower', 1, lambda value: value.lower() if value is not None else None,
            deterministic=True)
        connection.info['catalog_lower_ready'] = True


def apply_conditions(stmt, conditions, match, session):
    if not conditions:
        return stmt
    postgres = session.bind.dialect.name == 'postgresql'
    if not postgres:
        sqlite_lower(session)
    clauses = []
    lower = 'lower' if postgres else 'catalog_lower'
    for i, condition in enumerate(conditions):
        tag, _, code = condition.field.partition('$')
        params = {f'tag_{i}': tag}
        value = condition.value.lower()
        # Bind the search text. LIKE metacharacters always mean literal characters.
        if condition.operator == 'equals':
            params[f'value_{i}'] = value
        else:
            escaped = value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            params[f'value_{i}'] = ('%' if condition.operator == 'contains' else '') + escaped + '%'

        def compare(expression):
            if condition.operator in ('equals', 'starts_with'):
                # Strip surrounding whitespace only; phrase contents remain literal.
                trim = 'btrim' if postgres else 'trim'
                params[f'spaces_{i}'] = ' \t\n\r\u00a0'
                expression = f"{trim}({expression}, :spaces_{i})"
            if condition.operator == 'equals':
                return f"{lower}({expression}) = :value_{i}"
            return f"{lower}({expression}) LIKE :value_{i} ESCAPE '\\'"

        if tag == '000':
            expression = "records.marc->>'leader'" if postgres else "json_extract(records.marc, '$.leader')"
            clause = compare(expression)
            params.pop(f'tag_{i}')
        elif postgres:
            field_value, sub_value = "f->>'value'", "sf->>'value'"
            if code:
                params[f'code_{i}'] = code
                predicate = f"sf->>'code' = :code_{i} AND {compare(sub_value)}"
            else:
                predicate = compare(sub_value)
            if int(tag) < 10:
                predicate = compare(field_value)
            else:
                predicate = (f"EXISTS (SELECT 1 FROM jsonb_array_elements("
                             f"COALESCE(NULLIF(f->'subfields', 'null'::jsonb),'[]'::jsonb)) sf WHERE {predicate})")
            clause = (f"EXISTS (SELECT 1 FROM jsonb_array_elements(records.marc->'fields') f "
                      f"WHERE f->>'tag' = :tag_{i} AND {predicate})")
        else:
            field_value = "json_extract(f.value,'$.value')"
            sub_value = "json_extract(sf.value,'$.value')"
            if code:
                params[f'code_{i}'] = code
                predicate = f"json_extract(sf.value,'$.code') = :code_{i} AND {compare(sub_value)}"
            else:
                predicate = compare(sub_value)
            if int(tag) < 10:
                predicate = compare(field_value)
            else:
                predicate = (f"EXISTS (SELECT 1 FROM json_each(json_extract(f.value,'$.subfields')) sf "
                             f"WHERE {predicate})")
            clause = (f"EXISTS (SELECT 1 FROM json_each(json_extract(records.marc,'$.fields')) f "
                      f"WHERE json_extract(f.value,'$.tag') = :tag_{i} AND {predicate})")
        clauses.append(text(clause).bindparams(**params))
    return stmt.where((and_ if match == 'all' else or_)(*clauses))


class CatalogSearchInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    q: str = Field(default='', max_length=1000)
    udc: str = Field(default='', max_length=150)
    type_id: int | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)
    conditions: list[SearchCondition] = Field(default_factory=list, max_length=8)
    match: Literal['all', 'any'] = 'all'
