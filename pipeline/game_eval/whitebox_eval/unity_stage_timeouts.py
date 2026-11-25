"""Resolve independent stage budgets without evaluating absent legacy keys."""


def resolve(entry, protocol, stage, configuration=None):
    sources = (
        (entry.get('stage_timeouts', {}), stage),
        (protocol.get('runtime_budget', {}), stage+'_timeout_seconds'),
        (configuration or {}, stage+'_timeout_seconds'),
    )
    value = next((source[key] for source, key in sources if key in source), 900)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError('Invalid independent '+stage+' stage timeout')
    return value
