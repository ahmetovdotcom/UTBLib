from copy import deepcopy

import pytest

from app.catalog_udc import matches, select_udc
from app.db import Record
from test_catalog import client, field
from test_circulation import seed, session


@pytest.mark.parametrize('value,query,expected', [
    ('621.385', '62', True), ('519.862.6', '62', False),
    ('664.72', '72', False), ('664.724', '72', False), ('575(072)', '72', False),
    ('004.94', '94', False), ('95(94)"1945/..."', '94', False),
    ('633', '33', False), ('340.132.233', '33', False), ('334(075.8)', '34', False),
    ('94 (574)', '94', True), ('821.512.122-94', '94', False),
    ('811.512.122\'374=161.1', '37', False),
    ('[622+669](485)', '62', True), ('[622+669](485)', '66', True),
    ('004.384:[621.771.016.3:669.14]', '62', True),
    ('338.488.2:658.8', '33', True), ('338.488.2:658.8', '65', True),
    ('62(091)(574)', '9', False), ('62(091)(574)', '5', False),
    ('53(4+7)', '7', False), ('53"1972/1994"', '72', False),
    ('159,9', '159.9', True), ('3 - (Общественные науки)', '3', True),
    ('73/76', '74', True), ('73/76', '72', False), ('73/76', '7', True),
    ('73/76', '761', True), ('621.3/.5', '621.4', True), ('621.3/.5', '621.6', False),
    ('006;004.4', '004', True), ('8\'374.82;664', '664', True),
    ('004', '004', True), ('004', '04', False),
    ('621.3:004', '621.3:004', True), ('621.3:004', '(004)', False),
    ('ББК 72', '72', False), ('аб72', '72', False), ('575(072', '72', False),
    ('[72+004', '72', False), ('62/38', '62', False),
])
def test_subject_matching_excludes_auxiliaries_and_internal_digit_matches(value, query, expected):
    assert matches([value], query) is expected


@pytest.mark.parametrize('udc,shelf,expected,source', [
    (['6'], ['621.385'], ['621.385'], 'shelf_index'),
    (['00'], ['004'], ['004'], 'shelf_index'),
    ([], ['159,9'], ['159,9'], 'shelf_index'),
    (['3 - (Общественные науки)'], ['338.48'], ['338.48'], 'shelf_index'),
    (['6'], ['006'], ['006'], 'shelf_index'),
    (['621.3'], ['72'], ['621.3'], 'udc'),
    (['6', '004'], ['72'], ['6', '004'], 'udc'),
    (['6'], ['аб. 1', 'ББК 72', '575(072'], ['6'], 'udc'),
    (['6'], ['6'], ['6'], 'udc'),
    ([], ['аб72'], [], ''),
    ([], [], [], ''),
    (['6'], ['621.3', '621.3', 'аб1'], ['621.3'], 'shelf_index'),
])
def test_detailed_explicit_udc_has_priority_and_only_numeric_shelf_indices_are_used(udc, shelf, expected, source):
    assert select_udc(udc, shelf) == (expected, source)


def test_catalog_cards_filters_and_facets_share_effective_udc_without_rewriting_marc(client):
    _, _, rid = seed()
    with session() as s:
        record = s.get(Record, rid)
        marc = deepcopy(record.marc)
        marc['fields'] += [field('080', value='6'), field('090', value='621.385'),
                           field('090', 'f', 'PRIVATE_STORAGE')]
        record.marc = marc
        record.version += 1
        type_id = record.type_id
        # Former substring false positives and an actual architecture record.
        for index in ('664.72', '575(072)', '72.01', '004.94', '519.862.6'):
            s.add(Record(type_id=type_id, marc={'fields': [field(value='Книга '+index), field('080', value=index)]}, search_text=''))
        s.commit()
    root = '/api/public/v1'
    engineering = client.get(root+'/catalog', params={'udc': '62'}).json()
    assert engineering['meta']['total'] == 1
    assert engineering['data'][0]['id'] == f'utblib-{rid}'
    assert engineering['data'][0]['udc']['raw'] == '621.385'
    assert engineering['data'][0]['udc']['source'] == 'shelf_index'
    architecture = client.get(root+'/catalog', params={'udc': '72'}).json()
    assert architecture['meta']['total'] == 1
    assert architecture['data'][0]['udc']['raw'] == '72.01'
    assert client.get(root+'/catalog?udc=94').json()['meta']['total'] == 0
    assert client.get(root+'/books/utblib-'+str(rid)).json()['data']['udc']['raw'] == '621.385'
    facets = client.get(root+'/facets').json()['udc']
    assert {'value': '621.385', 'count': 1} in facets
    assert {'value': '6', 'count': 1} not in facets
    assert 'PRIVATE_STORAGE' not in str(engineering)
    with session() as s:
        record = s.get(Record, rid)
        assert record.marc == marc
        record.marc = {'fields': [field(value='Исправлено'), field('080', value='72.01'), field('090', value='621.385')]}
        record.version += 1
        s.commit()
    assert client.get(root+'/catalog?udc=62').json()['meta']['total'] == 0
    assert client.get(root+'/catalog?udc=72').json()['meta']['total'] == 2


def test_repeated_and_combined_indices_count_each_record_once_and_keep_faculty_privacy(client):
    _, _, rid = seed()
    with session() as s:
        record = s.get(Record, rid)
        record.is_faculty_work = True
        record.marc = {'fields': [field(value='Труд ППС'), field('080', value='6'),
                                 field('090', value='669.013:621.1'), field('090', value='621.3'),
                                 field('090', value='621.3')]}
        record.version += 1
        s.commit()
    response = client.get('/api/public/v1/catalog?udc=62').json()
    assert response['meta']['total'] == 1
    assert response['data'][0]['loginRequired'] is True
    assert response['data'][0]['udc']['raw'] == ''
    facets = client.get('/api/public/v1/facets').json()['udc']
    assert {'value': '621.3', 'count': 1} in facets
