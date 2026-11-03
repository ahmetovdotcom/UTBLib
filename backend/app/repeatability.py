"""Per-worksheet repetition rules; never mutate the source MARC dictionary."""
from copy import deepcopy


def locked(tag, code=None, local=False):
    return tag in ('000', '001', '005', '008') or (
        tag == '990' and local and (code is None or code in ('d', 'e', 'f'))
    )


def configured_spec(spec, config):
    result = deepcopy(spec)
    tag = config['tag']
    local = bool(config.get('local'))
    if locked(tag, local=local):
        result['repeatable'] = False
    elif config.get('repeatable') is not None:
        result['repeatable'] = config['repeatable']
    for sf in result.get('subfields', []):
        if locked(tag, sf['code'], local):
            sf['repeatable'] = False
        elif sf['code'] in config.get('subfield_repeatable', {}):
            sf['repeatable'] = config['subfield_repeatable'][sf['code']]
    return result
