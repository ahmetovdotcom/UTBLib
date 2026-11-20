"""Read-time UDC selection and subject matching; never rewrite source MARC.

The local MARCSQL profile often stores only a class in 080$a and the detailed
numeric index in 090$a. Alphabetic shelf marks are not classification numbers.
UDC signs: https://udcc.org/index.php/site/page?view=about_structure
"""
import re
import unicodedata


def normalize(value):
    value = unicodedata.normalize('NFKC', value).strip()
    value = value.translate(str.maketrans({'–': '-', '—': '-', '“': '"', '”': '"', '«': '"', '»': '"', '’': "'"}))
    value = re.sub(r'(?<=\d),(?=\d)', '.', value)
    # Legacy directory labels such as "3 - (Общественные науки)".
    value = re.sub(r'^(\d{1,2})\s+-\s+\([^)]*\)$', r'\1', value)
    return re.sub(r'\s+', '', value)


def subjects(value):
    """Main subject operands/ranges, excluding form, place, time and auxiliaries.

    This is deliberately a conservative recognizer, not a UDC authority validator.
    Unsupported/malformed shelf marks are not used as a fallback classification.
    """
    value = normalize(value)
    if not value or re.search(r'[^0-9.:+/;|()\[\]"\'=*\-]', value):
        return []
    visible, depth, groups, quoted = [], 0, 0, False
    for char in value:
        if char == '"':
            quoted = not quoted
        elif not quoted:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth < 0:
                    return []
            elif depth == 0:
                if char == '[':
                    groups += 1
                elif char == ']':
                    groups -= 1
                    if groups < 0:
                        return []
                visible.append(char)
    if depth or groups or quoted:
        return []
    # Auxiliary subdivisions/language/non-UDC notations never start a main subject.
    value = re.sub(r"[-'=*][^+:;|\[\]]*", '', ''.join(visible))
    result = []
    for part in re.split(r'[+:;|\[\]]+', value):
        if not part:
            continue
        ends = part.split('/')
        if len(ends) > 2 or not re.fullmatch(r'\d+(?:\.\d+)*\.?', ends[0]):
            return []
        first = ends[0].rstrip('.')
        last = first
        if len(ends) == 2:
            last = ends[1]
            if last.startswith('.') and '.' in first:
                last = first.rsplit('.', 1)[0] + last
            if not re.fullmatch(r'\d+(?:\.\d+)*\.?', last):
                return []
        first, last = first.replace('.', ''), last.replace('.', '')
        if first > last:
            return []
        result.append((first, last))
    return result


def select_udc(udc, shelf):
    parsed = [subjects(value) for value in udc]
    # A detailed explicit 080 always wins. 0/00 and the single-digit classes are broad.
    coarse = not udc or all(parts and all(a == b and (len(a) == 1 or a == '00') for a, b in parts)
                           for parts in parsed)
    fallback = [value for value in shelf if subjects(value)]
    if coarse and any(any(len(a) > 1 and a != '00' for a, _ in subjects(value)) for value in fallback):
        return list(dict.fromkeys(fallback)), 'shelf_index'
    return list(dict.fromkeys(udc)), 'udc' if udc else ''


def matches(values, query):
    query = normalize(query)
    if not query:
        return True
    if not re.fullmatch(r'\d+(?:\.\d+)*', query):
        return any(normalize(value) == query for value in values)
    code = query.replace('.', '')
    for value in values:
        for first, last in subjects(value):
            if first == last:
                if first.startswith(code):
                    return True
            elif first.startswith(code) or last.startswith(code) or code.startswith(last) or first <= code <= last:
                return True
    return False
