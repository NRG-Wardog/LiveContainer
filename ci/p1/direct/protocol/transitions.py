"""Validate actual transition receipts. No timing or pixel acceptance implied."""

def receipt(row):
    value=row.get("receiptNs")
    if not isinstance(value, (tuple,list)) or len(value)!=2 or any(type(x) is not int or x<0 for x in value) or value[0]>value[1]:
        raise ValueError("conservative receipt interval required")
    return value

def validate(scenario, clipboard, transitions):
    if scenario not in ('timeout', 'replacement', 'dismissal'):
        raise ValueError('unknown scenario')
    expected_count = 1 if scenario == 'timeout' else 3
    if len(clipboard) != expected_count:
        raise ValueError('clipboard inventory')
    for index, row in enumerate(clipboard, 1):
        if type(row.get('ordinal')) is not int or row['ordinal'] != index:
            raise ValueError('clipboard ordinal')
        if row.get('clipboardExact') is not True or row.get('shown') is not True:
            raise ValueError('clipboard context')
        if type(row.get('generation')) is not int or row['generation'] < 0:
            raise ValueError('generation')
        if type(row.get('changeCount')) is not int or row['changeCount'] < 0:
            raise ValueError('change count')
        if not isinstance(row.get('payload'), str) or not row['payload'] or row['payload'] != row.get('expectedPayload'):
            raise ValueError('payload')
        receipt(row)
        driver = 'normal-XCTest-tap' if index == 1 else 'experimental-XCTest-coordinate-tap' if index == 2 else 'normal-XCTest-third-tap'
        if row.get('driver') != driver:
            raise ValueError('input driver')
        if index > 1 and (receipt(row)[0] <= receipt(clipboard[index-2])[1] or row['changeCount'] <= clipboard[index-2]['changeCount']):
            raise ValueError('non-distinct clipboard event')
    kinds = [] if scenario == 'timeout' else ['replace'] if scenario == 'replacement' else ['dismiss', 'reopen']
    if len(transitions) != len(kinds):
        raise ValueError('transition inventory')
    generation = clipboard[0]['generation']
    if scenario != 'timeout' and generation != 0:
        raise ValueError('original overlap fixture must begin at generation zero')
    previous = receipt(clipboard[0])[1]
    for row, kind in zip(transitions, kinds):
        expected_generation = generation + 1 if kind == 'replace' else generation
        if row.get('kind') != kind or type(row.get('generation')) is not int or row['generation'] != expected_generation:
            raise ValueError('transition identity/order')
        if row.get('shown') is not (kind != 'dismiss'):
            raise ValueError('transition visibility')
        if not previous < receipt(row)[0] or not receipt(row)[1] < receipt(clipboard[1])[0]:
            raise ValueError('transition did not precede second event')
        previous = receipt(row)[1]
    if scenario != 'timeout':
        expected = generation + (scenario == 'replacement')
        if clipboard[1]['generation'] != expected or clipboard[2]['generation'] != expected:
            raise ValueError('later clipboard identity')
        if clipboard[1]['payload'] != clipboard[2]['payload']:
            raise ValueError('third payload identity')
        if scenario == 'replacement' and clipboard[0]['payload'] == clipboard[1]['payload']:
            raise ValueError('replacement diagnostic unchanged')
        if scenario == 'dismissal' and clipboard[0]['payload'] != clipboard[1]['payload']:
            raise ValueError('same-identity dismissal changed diagnostic')
    return {'scope':'transition-receipts-only','scenario':scenario,'admissionEligible':False}


def uptime_interval_ns(value):
    """Outward envelope of serialized Double uptime, not delivery latency.

    Neighboring representable values conservatively include binary rounding.
    This never turns a notification receipt into production write/timer time.
    """
    import math
    from fractions import Fraction
    if type(value) is not float or not math.isfinite(value) or value < 0:
        raise ValueError('finite nonnegative native Double uptime required')
    low = max(0.0, math.nextafter(value, -math.inf))
    high = math.nextafter(value, math.inf)
    if not math.isfinite(high):
        raise ValueError('uptime overflow')
    lower, upper = Fraction(low) * 1_000_000_000, Fraction(high) * 1_000_000_000
    return lower.numerator // lower.denominator, -((-upper.numerator) // upper.denominator)
