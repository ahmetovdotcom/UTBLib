"""Token usage from the Responses envelope, never from model-generated text."""
from decimal import Decimal


# Standard USD / 1M tokens. Verified 2026-10-27 against the model pages below.
# Exact model IDs only: do not silently price an unknown model/snapshot as Terra.
PRICES = {
    'gpt-5.6-terra': ('2', '0.20', '12'),
    'gpt-6.1-terra': ('1', '0.05', '5'),
}
PRICING_DATE = '2026-10-27'


def token_count(value):
    return value if type(value) is int and 0 <= value <= 10_000_000 else None


def response_usage(response, requested_model):
    """Missing/invalid accounting must not hide a good description or imply zero cost."""
    model = response.get('model')
    if not isinstance(model, str) or not model or len(model) > 200:
        model = None
    raw = response.get('usage')
    raw = raw if isinstance(raw, dict) else {}
    details = raw.get('input_tokens_details')
    details = details if isinstance(details, dict) else {}
    output_details = raw.get('output_tokens_details')
    output_details = output_details if isinstance(output_details, dict) else {}
    incoming, outgoing, total = (token_count(raw.get(k)) for k in (
        'input_tokens', 'output_tokens', 'total_tokens'))
    cached = token_count(details.get('cached_tokens'))
    written = token_count(details.get('cache_write_tokens'))
    reasoning = token_count(output_details.get('reasoning_tokens'))
    result = {
        'model': model or requested_model,
        'input_tokens': incoming, 'output_tokens': outgoing, 'total_tokens': total,
        'cached_input_tokens': cached, 'cache_write_tokens': written,
        'reasoning_tokens': reasoning if outgoing is not None and reasoning is not None and reasoning <= outgoing else None,
        'estimated_cost_usd': None, 'pricing_date': None, 'pricing_url': None,
        'cost_note': 'OpenAI не передал полный расход токенов. Стоимость неизвестна.',
    }
    if incoming is None or outgoing is None or total is None:
        return result
    if total != incoming + outgoing:
        result['total_tokens'] = None
        result['cost_note'] = 'Счётчики OpenAI не согласованы. Стоимость не рассчитана.'
        return result
    if model not in PRICES:
        result['cost_note'] = 'Для этой модели нет проверенного тарифа. Токены показаны без стоимости.'
        return result
    # The caller explicitly requests default/Standard, with no tools or regional endpoint.
    if response.get('service_tier', 'default') != 'default' or incoming > 272_000:
        result['cost_note'] = 'Для этого режима обработки или размера запроса тариф не настроен.'
        return result
    if cached is None or written is None or cached + written > incoming:
        result['cost_note'] = 'Нет корректной разбивки входящих токенов по кэшу. Стоимость неизвестна.'
        return result
    # No retention override is sent. Older envelopes omit lifetime details and use
    # the documented default 30-minute write rate. New envelopes can report both.
    lifetimes = details.get('cache_write_tokens_details')
    short, long = written, 0
    if lifetimes is not None:
        if not isinstance(lifetimes, dict):
            short = long = None
        else:
            short = token_count(lifetimes.get('ttl_30m_tokens'))
            long = token_count(lifetimes.get('ttl_12h_tokens'))
        if short is None or long is None or short + long != written:
            result['cost_note'] = 'Нет корректной разбивки записи в кэш. Стоимость неизвестна.'
            return result
    price_in, price_cached, price_out = map(Decimal, PRICES[model])
    amount = (
        (incoming - cached - written) * price_in + cached * price_cached
        + short * price_in * Decimal('1.25') + long * price_in * Decimal('2.5')
        + outgoing * price_out
    ) / Decimal(1_000_000)
    result.update(
        estimated_cost_usd=format(amount, 'f'), pricing_date=PRICING_DATE,
        pricing_url='https://developers.openai.com/api/docs/models/' + model,
        cost_note='Оценка по стандартному тарифу OpenAI, с учётом кэша, без налогов и индивидуальных условий аккаунта.',
    )
    return result
