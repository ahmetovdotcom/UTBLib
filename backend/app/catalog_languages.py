"""Read-time language normalization; never rewrite the original MARC fields.

041$a is repeatable. Older catalogues also concatenate three-letter codes.
Reference: https://www.loc.gov/marc/bibliographic/bd041.html
"""
import re


LANGUAGE_ALIASES = {
    'ru': ('ru', 'rus', 'рус'), 'kk': ('kk', 'kaz', 'kz', 'каз', 'қаз'),
    'en': ('en', 'eng'), 'de': ('de', 'ger', 'deu'), 'fr': ('fr', 'fre', 'fra'),
    'zh': ('zh', 'chi', 'zho'), 'tr': ('tr', 'tur'), 'ar': ('ar', 'ara'),
    'uz': ('uz', 'uzb'), 'ky': ('ky', 'kir'), 'tg': ('tg', 'tgk'),
    'tk': ('tk', 'tuk'), 'tt': ('tt', 'tat'), 'uk': ('uk', 'ukr'),
    'be': ('be', 'bel'), 'az': ('az', 'aze'), 'ka': ('ka', 'geo', 'kat'),
    'hy': ('hy', 'arm', 'hye'), 'ja': ('ja', 'jpn'), 'ko': ('ko', 'kor'),
    'es': ('es', 'spa'), 'it': ('it', 'ita'), 'pt': ('pt', 'por'),
    'fa': ('fa', 'per', 'fas'), 'la': ('la', 'lat'), 'pl': ('pl', 'pol'),
    'cs': ('cs', 'cze', 'ces'), 'el': ('el', 'gre', 'ell'), 'mn': ('mn', 'mon'),
    'hi': ('hi', 'hin'), 'he': ('he', 'heb'),
    'mul': ('mul',), 'und': ('und',), 'zxx': ('zxx',),
}
_CODES = {alias: code for code, aliases in LANGUAGE_ALIASES.items() for alias in aliases}


def language(value):
    return _CODES.get(value.strip().casefold(), 'other')


def languages(values):
    """Preserve source order, deduplicate, and keep unknown tokens as 'other'."""
    result = []
    for value in values:
        for token in re.split(r'[\s,;:/+|&.()\[\]—–-]+', value.strip().casefold()):
            if not token:
                continue
            if token in _CODES:
                result.append(_CODES[token])
            elif re.fullmatch(r'(?:[a-z]{3}){2,}', token):
                chunks = [token[i:i + 3] for i in range(0, len(token), 3)]
                # Do not infer languages from arbitrary words or partially valid codes.
                result.extend([_CODES[x] for x in chunks] if all(x in _CODES for x in chunks) else ['other'])
            else:
                result.append('other')
    return list(dict.fromkeys(result))
