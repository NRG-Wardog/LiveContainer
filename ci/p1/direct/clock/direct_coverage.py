"""Conservative point-observation coverage; never invent frame persistence."""
from fractions import Fraction
from direct_clock import interval, app_time_ns, integer, COMBINED_LIMIT_NS


def coverage(records, mapping, baseline, finish):
    baseline, finish = interval(*baseline), interval(*finish)
    if finish[0] <= baseline[1]:
        raise ValueError('invalid protocol boundaries')
    if not records:
        raise ValueError('empty stream')
    observations = []
    previous_display = None
    timebase = None
    for index, row in enumerate(records):
        if row.get('ordinal') != index + 1 or type(row.get('ordinal')) is not int:
            raise ValueError('record inventory')
        status = row.get('status')
        if status not in ('complete', 'idle', 'started', 'stopped'):
            raise ValueError('unknown or invalid status')
        if row.get('error') is not None:
            raise ValueError('record error')
        if status != 'complete':
            # These records remain in inventory, but provide no pixel observation.
            continue
        current = (row['timebaseNumer'], row['timebaseDenom'])
        if timebase is not None and current != timebase:
            raise ValueError('timebase changed')
        timebase = current
        app = app_time_ns(row['displayTicks'], *current, mapping)
        if app[1] - app[0] > COMBINED_LIMIT_NS:
            raise ValueError('combined mapping too wide')
        ticks = integer(row['displayTicks'], 'display ticks', positive=True)
        display = Fraction(ticks * current[0], current[1])
        if previous_display is not None and display <= previous_display:
            raise ValueError('nonmonotonic display timestamp')
        previous_display = display
        # Pixel/source verification is a separate mandatory stage, not inferred here.
        observations.append(dict(record=index + 1, displayNs=display, appNs=app))
    if len(observations) < 2:
        raise ValueError('insufficient complete observations')
    before = [i for i, row in enumerate(observations) if row['appNs'][1] <= baseline[0]]
    after = [i for i, row in enumerate(observations) if row['appNs'][0] >= finish[1]]
    if not before or not after:
        raise ValueError('uncertain boundaries not covered')
    start, end = before[-1], after[0]
    if end <= start:
        raise ValueError('reversed coverage')
    selected = observations[start:end + 1]
    for left, right in zip(selected, selected[1:]):
        if right['displayNs'] - left['displayNs'] > COMBINED_LIMIT_NS:
            raise ValueError('inter-observation gap exceeds 120 ms')
    return {'scope': 'point-observation-coverage-only',
            'firstRecord': selected[0]['record'], 'lastRecord': selected[-1]['record'],
            'observations': selected, 'admissionEligible': False}
