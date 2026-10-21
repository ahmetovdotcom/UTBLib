"""Parser for the DOC.ITEM dialect observed in the supplied MARCSQL samples.

The original ITEM must always be archived: this is not an ISO2709 decoder.
"""
import hashlib
import json
import re


def fingerprint(item, rectype, biblevel):
    return hashlib.sha256(json.dumps([item, rectype, biblevel], ensure_ascii=False).encode()).hexdigest()


def parse_item(item, rectype, biblevel):
    if not item or len(rectype) != 1 or len(biblevel) != 1:
        raise ValueError('Пустая запись или неверный тип/уровень')
    leader = list('00000nam a2200000   4500')
    leader[6], leader[7] = rectype, biblevel
    fields, warnings = [], []
    blocks = item.split('\x1e')
    if blocks[-1] == '':
        blocks.pop()
    for block in blocks:
        if len(block) < 5 or not re.fullmatch(r'\d{3}', block[:3]):
            raise ValueError('Неизвестный заголовок поля')
        tag = block[:3]
        parts = block[5:].split('\x1f')
        if parts[0] or len(parts) < 2 or any(not p for p in parts[1:]):
            raise ValueError(f'{tag}: неизвестная структура подполей')
        pairs = [(p[0], p[1:]) for p in parts[1:]]
        if int(tag) < 10:
            values = [v for c, v in pairs if c == '0']
            if len(values) != 1:
                raise ValueError(f'{tag}: ожидалось одно служебное подполе 0')
            if len(pairs) > 1:
                warnings.append(f'{tag}: дополнительные данные сохранены в оригинале ITEM')
            if tag == '000':
                if len(values[0]) > 5:
                    leader[5] = values[0][5]
                warnings.append('000: маркер построен для приложения; исходный маркер сохранён в ITEM')
            else:
                fields.append({'tag': tag, 'value': values[0]})
        else:
            if any(not re.fullmatch('[a-z0-9]', c) for c, _ in pairs):
                raise ValueError(f'{tag}: неподдерживаемый код подполя')
            fields.append({'tag': tag, 'ind1': block[3], 'ind2': block[4],
                           'subfields': [{'code': c, 'value': v} for c, v in pairs]})
    return {'leader': ''.join(leader), 'fields': fields}, warnings
