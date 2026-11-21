from dataclasses import dataclass


WORK_UNIT = 'work'


@dataclass(frozen=True, slots=True)
class WorkPolicy:
    version: str
    multipliers: tuple[tuple[str, int], ...]


_POLICIES = {
    'line-v1': WorkPolicy('line-v1', (('tick', 2), ('cycle', 5))),
    'bench-v1': WorkPolicy('bench-v1', (('tick', 3), ('cycle', 5))),
}


def get_policy(version: str) -> WorkPolicy:
    if type(version) is not str or version not in _POLICIES:
        raise ValueError('unknown work policy')
    return _POLICIES[version]


def to_work_units(policy: WorkPolicy, amount: int, unit: str = WORK_UNIT) -> int:
    if type(amount) is not int or amount < 0:
        raise ValueError('work amount must be a nonnegative integer')
    if unit == WORK_UNIT:
        return amount
    for name, multiplier in policy.multipliers:
        if name == unit:
            return amount * multiplier
    raise ValueError(f'unknown timing unit {unit!r} for {policy.version}')
