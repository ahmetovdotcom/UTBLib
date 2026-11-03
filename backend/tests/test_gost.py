from app.gost import describe
from app.worksheet import default_config, definitions
from app.main import DICTIONARY
from app.validation import validate_config, validate_marc

def field(tag,**subs):return {'tag':tag,'ind1':' ','ind2':' ','subfields':[{'code':c,'value':v} for c,v in subs.items()]}
def marc(*fields):return {'leader':'00000nam a2200000   4500','fields':list(fields)}
def test_description_order_and_punctuation():
    m=marc(field('020',a='978-5-00000-000-0'),field('245',a='Книга',c='И. И. Иванов',z='Текст : непосредственный'),field('260',a='Москва',b='Издатель',c='2020'),field('300',a='120 с.'))
    result=describe(m)
    assert result['text']=='Книга / И. И. Иванов. — Москва : Издатель, 2020. — 120 с. — ISBN 978-5-00000-000-0. — Текст : непосредственный.'
    assert result['requires_review'] is True
    assert not result['issues']
def test_author_not_fabricated_as_responsibility():
    result=describe(marc(field('245',a='Книга'),field('100',a='Иванов, Иван')))
    assert 'Иванов' not in result['text']
    assert any(x['code']=='responsibility' for x in result['issues'])
def test_component_requires_host_and_preserves_local_fields_outside_output():
    result=describe(marc(field('245',a='Статья',c='Автор',z='Текст : непосредственный'),field('773',t='Журнал',g='2020. — № 1. — С. 2–5'),field('952',d='Факультет')),'component')
    assert ' // Журнал' in result['text']
    assert 'Факультет' not in result['text']
    assert not any(x['code']=='host' for x in result['issues'])
    assert any(x['code']=='host' for x in describe(marc(field('245',a='Статья')),'component')['issues'])
def test_local_profile_is_separate_and_matches_screenshot_order():
    local=definitions(DICTIONARY);config=default_config()
    assert not validate_config(config,DICTIONARY,local)
    screenshot=['000','001','005','008','013','020','040','041','080','090','097','100','245','260','300','653','952','990','336','337']
    assert [x['tag'] for x in config if x['tag'] in screenshot]==screenshot
    assert '097' not in DICTIONARY and local['097']['local']
    assert [s['code'] for s in local['090']['subfields']]==['a','f','c','x']
    assert next(c for c in config if c['tag']=='653')['subfields']==['a']
def test_marker_is_not_a_data_field_and_local_subfields_roundtrip():
    config=default_config();dictionary={**DICTIONARY,**definitions(DICTIONARY)}
    f=field('245',a='Книга');f['ind1']='1';f['ind2']='0'
    m=marc(f,field('952',d='Факультет',j='Специальность'),field('990',f='20.10.2026'))
    errors,warnings=validate_marc(m,config,dictionary)
    assert not errors
    m['fields'].append({'tag':'000','value':'n'})
    assert any('000' in x for x in validate_marc(m,config,dictionary)[0])

def test_legacy_series_from_new_worksheet():
    result=describe(marc(field('245',a='Книга'),field('440',a='Учебная серия')))
    assert '(Учебная серия)' in result['text']


def test_record_heading_is_separate_from_transcribed_responsibility():
    result=describe(marc(field('100',a='Асанов, М. К.'),field('245',a='Қазақстан тарихы',c='Марат Асанов')))
    assert result['text']=='Қазақстан тарихы / Марат Асанов.'
    assert result['record_text']=='Асанов, М. К. Қазақстан тарихы / Марат Асанов.'
    missing=describe(marc(field('100',a='Асанов, М. К.'),field('245',a='Қазақстан тарихы')))
    assert missing['record_text']=='Асанов, М. К. Қазақстан тарихы.'
    assert ' / ' not in missing['record_text']
    assert any(i['code']=='responsibility' for i in missing['issues'])
    assert describe(marc(field('100',d='1900–1980'),field('245',a='Книга')))['heading']==''


def test_book_example_from_standard_appendix_a():
    result=describe(marc(
        field('100',a='Каменский, П. П.'),
        field('245',a='Труды по истории изобразительного искусства',b='художественная критика',
              c='П. П. Каменский ; составитель, автор вступительной статьи и примечаний Н. С. Беляев ; Библиотека Российской академии наук',z='Текст : непосредственный'),
        field('260',a='Санкт-Петербург',b='БАН',c='2017'),field('300',a='215, [1] с.',b='портр.',c='21 см'),
        field('500',a='Библиогр. в подстроч. примеч.'),field('500',a='Имен. указ.: с. 206–215'),
        field('500',a='300 экз. (1-й з-д 1–100)'),field('020',a='978-5-336-00204-1'),
    ))
    assert result['record_text']==(
        'Каменский, П. П. Труды по истории изобразительного искусства : художественная критика / '
        'П. П. Каменский ; составитель, автор вступительной статьи и примечаний Н. С. Беляев ; '
        'Библиотека Российской академии наук. — Санкт-Петербург : БАН, 2017. — 215, [1] с. : портр. ; 21 см. — '
        'Библиогр. в подстроч. примеч. — Имен. указ.: с. 206–215. — 300 экз. (1-й з-д 1–100). — '
        'ISBN 978-5-336-00204-1. — Текст : непосредственный.')
    assert not result['issues']


def test_prescribed_punctuation_already_in_marc_is_not_repeated():
    import copy
    m=marc(field('245',a='А/Б: выбор! :',b='учебник /',c='И. И. Иванов.'),
           field('250',a='2-е изд. /',b='под редакцией А. Б. Петрова'),
           field('260',a='Алматы :',b='Издатель,',c='2026.'),
           field('300',a='120 с. :',b='ил. ;',c='21 см +',e='1 карта'))
    original=copy.deepcopy(m)
    result=describe(m)
    assert result['text']==('А/Б: выбор! : учебник / И. И. Иванов. — 2-е изд. / под редакцией А. Б. Петрова. — '
                            'Алматы : Издатель, 2026. — 120 с. : ил. ; 21 см + 1 карта.')
    assert m==original


def test_series_issn_and_repeated_series_and_blank_490_fallback():
    result=describe(marc(field('245',a='Книга'),field('490',a=''),
        field('440',a='Структурная и прикладная лингвистика',x='0202-2400',v='вып. 8'),
        field('440',a='Учебная серия',v='3')))
    assert '(Структурная и прикладная лингвистика, ISSN 0202-2400 ; вып. 8) (Учебная серия ; 3).' in result['text']
    preferred=describe(marc(field('245',a='Книга'),field('490',a='Новая серия'),field('440',a='Старая серия')))
    assert '(Новая серия)' in preferred['text'] and 'Старая серия' not in preferred['text']


def test_identifier_qualifiers_and_language_preserved():
    result=describe(marc(field('245',a='The spiritual heritage',c='A. Author'),
                         field('020',a='ISBN 978-0-123456-78-9',q='paperback')))
    assert result['record_text']=='The spiritual heritage / A. Author. — ISBN 978-0-123456-78-9 (paperback).'
    assert 'None' not in result['text']
