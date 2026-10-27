import copy
from decimal import Decimal

import pytest

from app.book_photo_usage import response_usage


def envelope(model='gpt-5.6-terra', incoming=10000, outgoing=1000, cached=0, written=0):
    return {'model': model, 'service_tier': 'default', 'usage': {
        'input_tokens': incoming, 'output_tokens': outgoing, 'total_tokens': incoming + outgoing,
        'input_tokens_details': {'cached_tokens': cached, 'cache_write_tokens': written},
        'output_tokens_details': {'reasoning_tokens': 400},
    }}


def test_standard_cost_includes_photos_and_reasoning_only_once():
    result = response_usage(envelope(), 'gpt-5.6-terra')
    assert result['total_tokens'] == 11000
    assert result['reasoning_tokens'] == 400
    assert Decimal(result['estimated_cost_usd']) == Decimal('0.032')
    assert result['pricing_date'] == '2026-10-27'


def test_cache_read_and_write_are_disjoint_parts_of_input():
    result = response_usage(envelope(cached=4000, written=3000), 'gpt-5.6-terra')
    # 3000 ordinary × $2 + 4000 cached × $0.20 + 3000 writes × $2.50 + 1000 output × $12.
    assert Decimal(result['estimated_cost_usd']) == Decimal('0.0263')
    assert result['input_tokens'] == 10000 and result['total_tokens'] == 11000


def test_separate_cache_write_lifetimes():
    response = envelope(cached=4000, written=3000)
    response['usage']['input_tokens_details']['cache_write_tokens_details'] = {
        'ttl_30m_tokens': 1000, 'ttl_12h_tokens': 2000}
    assert Decimal(response_usage(response, 'gpt-5.6-terra')['estimated_cost_usd']) == Decimal('0.0313')


def test_actual_model_controls_price_not_requested_model():
    result = response_usage(envelope(model='gpt-6.1-terra', cached=4000, written=3000), 'gpt-5.6-terra')
    assert result['model'] == 'gpt-6.1-terra'
    assert Decimal(result['estimated_cost_usd']) == Decimal('0.01195')


@pytest.mark.parametrize('change', [
    lambda r: r.pop('usage'),
    lambda r: r.update(usage=None),
    lambda r: r['usage'].update(input_tokens=-1),
    lambda r: r['usage'].update(output_tokens=True),
    lambda r: r['usage'].update(total_tokens=0),
    lambda r: r['usage'].update(input_tokens='10000'),
    lambda r: r['usage'].update(input_tokens_details=None),
    lambda r: r['usage']['input_tokens_details'].pop('cache_write_tokens'),
    lambda r: r['usage']['input_tokens_details'].update(cached_tokens=9000, cache_write_tokens=3000),
    lambda r: r['usage']['input_tokens_details'].update(cache_write_tokens_details={'ttl_30m_tokens': 1, 'ttl_12h_tokens': 0}),
    lambda r: r['usage']['input_tokens_details'].update(cache_write_tokens_details=[]),
    lambda r: r.update(model='unknown-model'),
    lambda r: r.update(model='gpt-5.6-terra-unknown-snapshot'),
    lambda r: r.pop('model'),
    lambda r: r.update(service_tier='priority'),
])
def test_unknown_accounting_is_not_zero_or_estimated_with_wrong_rate(change):
    response = envelope()
    change(response)
    before = copy.deepcopy(response)
    result = response_usage(response, 'gpt-5.6-terra')
    assert result['estimated_cost_usd'] is None
    assert result['cost_note']
    assert response == before


def test_long_context_has_no_unverified_estimate_and_zero_is_distinct_from_missing():
    assert response_usage(envelope(incoming=272001), 'gpt-5.6-terra')['estimated_cost_usd'] is None
    result = response_usage(envelope(incoming=0, outgoing=0), 'gpt-5.6-terra')
    assert Decimal(result['estimated_cost_usd']) == 0
    assert result['total_tokens'] == 0
    assert result['reasoning_tokens'] is None
    missing = response_usage({}, 'gpt-5.6-terra')
    assert missing['total_tokens'] is None and missing['estimated_cost_usd'] is None
