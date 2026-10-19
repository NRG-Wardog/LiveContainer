"""Exact clock-validation primitive. No capture or feedback acceptance is granted."""
from fractions import Fraction

PHASES = ('pre', 'mid', 'post')
APP_LIMIT_NS = 20_000_000
COMBINED_LIMIT_NS = 120_000_000


def integer(value, label, *, positive=False):
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError(label)
    return value


def rational(value):
    if isinstance(value, bool) or not isinstance(value, (int, Fraction)):
        raise ValueError('exact rational required')
    return Fraction(value)


def interval(low, high):
    low, high = rational(low), rational(high)
    if low > high:
        raise ValueError('reversed interval')
    return low, high


def intersection(rows):
    if not rows:
        raise ValueError('empty observations')
    values = [interval(*row) for row in rows]
    return interval(max(x[0] for x in values), min(x[1] for x in values))


def mach_bracket(row):
    """Host-minus-mach nanoseconds; raw UInt64 ticks never pass through float."""
    before = integer(row['hostBeforeNs'], 'host before')
    after = integer(row['hostAfterNs'], 'host after')
    ticks = integer(row['machTicks'], 'mach ticks', positive=True)
    numer = integer(row['timebaseNumer'], 'timebase numerator', positive=True)
    denom = integer(row['timebaseDenom'], 'timebase denominator', positive=True)
    if ticks > 2**64 - 1 or numer > 2**32 - 1 or denom > 2**32 - 1:
        raise ValueError('native integer overflow')
    if after < before:
        raise ValueError('host clock reversed')
    converted = Fraction(ticks * numer, denom)
    return interval(before - converted, after - converted)


def phase_bridge(rows, *, count=8):
    """All eight samples per phase, no fastest-sample selection or fitting."""
    if type(count) is not int or count != 8 or len(rows) != 24:
        raise ValueError('exact three-phase inventory required')
    phases = {}
    timebase = None
    prior_host = None
    for phase in PHASES:
        batch = rows[len(phases)*count:(len(phases)+1)*count]
        values = []
        for ordinal, row in enumerate(batch, 1):
            if row.get('phase') != phase or row.get('ordinal') != ordinal or type(row.get('ordinal')) is not int:
                raise ValueError('phase/ordinal inventory')
            current = (row['timebaseNumer'], row['timebaseDenom'])
            if timebase is not None and current != timebase:
                raise ValueError('timebase changed')
            timebase = current
            value = mach_bracket(row)
            if prior_host is not None and row['hostBeforeNs'] < prior_host:
                raise ValueError('overlapping or reversed host exchanges')
            prior_host = row['hostAfterNs']
            values.append(value)
        phases[phase] = intersection(values)
    common = intersection(list(phases.values()))
    return phases, common


def combine(app_host_phases, host_mach_phases):
    """Inputs are measured app-minus-host and host-minus-mach intervals, in ns."""
    if set(app_host_phases) != set(PHASES) or set(host_mach_phases) != set(PHASES):
        raise ValueError('missing or foreign phase')
    combined = {}
    for phase in PHASES:
        app = interval(*app_host_phases[phase])
        host = interval(*host_mach_phases[phase])
        if app[1] - app[0] > APP_LIMIT_NS:
            raise ValueError('app/host phase exceeds 20 ms')
        value = interval(app[0] + host[0], app[1] + host[1])
        serialized = outward_ns(value)
        if value[1] - value[0] > COMBINED_LIMIT_NS or serialized[1] - serialized[0] > COMBINED_LIMIT_NS:
            raise ValueError('combined phase exceeds 120 ms')
        combined[phase] = value
    # Compatibility is mandatory separately for both domains and the sum.
    intersection(list(app_host_phases.values()))
    intersection(list(host_mach_phases.values()))
    return combined, intersection(list(combined.values()))


def outward_ns(value):
    """Serialize a rational interval conservatively to integer nanoseconds."""
    low, high = interval(*value)
    return low.numerator // low.denominator, -((-high.numerator) // high.denominator)


def app_time_ns(display_ticks, numer, denom, app_minus_mach):
    row = dict(hostBeforeNs=0, hostAfterNs=0, machTicks=display_ticks,
               timebaseNumer=numer, timebaseDenom=denom)
    neg, _ = mach_bracket(row)
    low, high = interval(*app_minus_mach)
    result = interval(-neg + low, -neg + high)
    serialized = outward_ns(result)
    if serialized[1] - serialized[0] > COMBINED_LIMIT_NS:
        raise ValueError("final mapped serialization exceeds 120 ms")
    return result


def sample(phase, ordinal, native_reader, monotonic_ns):
    """Take one in-process causal bracket; dependency injection is for tests."""
    if phase not in PHASES or type(ordinal) is not int or not 1 <= ordinal <= 8:
        raise ValueError('phase/ordinal')
    before = monotonic_ns()
    ticks, numer, denom = native_reader()
    after = monotonic_ns()
    row = dict(phase=phase, ordinal=ordinal, hostBeforeNs=before,
               hostAfterNs=after, machTicks=ticks, timebaseNumer=numer,
               timebaseDenom=denom)
    mach_bracket(row)
    return row


def darwin_reader():
    """Bind Apple's public APIs in the current process. No helper subprocess."""
    import ctypes
    import sys
    if sys.platform != 'darwin':
        raise RuntimeError('native mach sampling requires Darwin')
    lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
    class Timebase(ctypes.Structure):
        _fields_ = [('numer', ctypes.c_uint32), ('denom', ctypes.c_uint32)]
    lib.mach_timebase_info.argtypes = [ctypes.POINTER(Timebase)]
    lib.mach_timebase_info.restype = ctypes.c_int
    lib.mach_absolute_time.argtypes = []
    lib.mach_absolute_time.restype = ctypes.c_uint64
    info = Timebase()
    if lib.mach_timebase_info(ctypes.byref(info)) != 0 or not info.numer or not info.denom:
        raise RuntimeError('mach timebase unavailable')
    return lambda: (int(lib.mach_absolute_time()), int(info.numer), int(info.denom))
