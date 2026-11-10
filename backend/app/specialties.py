"""The catalogue is the sole source of primary specialty for every KSU report."""
from fastapi import HTTPException
from .db import KsuEntry
from .ksu_auto import vals


def choices(marc):
    return sorted(vals(marc,'952','j'))


def primary(marc, selected=None):
    values=choices(marc)
    selected=(selected or '').strip()
    return selected if selected in values else (values[0] if len(values)==1 else None)


def entry_allocations(s, entry_id):
    from .ksu_data import grouped_members, entry_output
    entry=s.get(KsuEntry,entry_id)
    if not entry:raise HTTPException(404,'КСУ не найдена')
    items={}
    for line,record in grouped_members(s,[entry_id]).get(entry_id,[]):
        selected=primary(record.marc,record.primary_specialty)
        item=items.setdefault(record.id,{'record_id':record.id,
            'title':' '.join(sorted(vals(record.marc,'245','a'))) or line.title_snapshot,'copies':0,
            'primary_specialty':selected,
            'additional_specialties':[value for value in choices(record.marc) if value!=selected]})
        item['copies']+=line.quantity
    return {'entry':entry_output(entry),'items':list(items.values())}
