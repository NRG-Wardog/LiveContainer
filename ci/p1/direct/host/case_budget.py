"""Conservative absolute Mach cutoffs anchored before the original command.

The parent still owns every process and independently enforces its Scope and
360-second command allowance. These cutoffs never establish clock equivalence
for pixel timing; they only prevent helper stages from resetting time budgets.
"""
from fractions import Fraction

MAX_TICK=2**64-1

def integer(v,lo=0,hi=MAX_TICK):
    if type(v) is not int or not lo<=v<=hi:raise ValueError('bounded exact budget integer')
    return v

def construct(start_sample,scope_remaining_ns):
    if type(start_sample) is not dict or set(start_sample)!={'hostBeforeNs','hostAfterNs','machTicks','timebaseNumer','timebaseDenom'}:raise ValueError('exact start bracket')
    before=integer(start_sample['hostBeforeNs']);after=integer(start_sample['hostAfterNs'])
    if after<before:raise ValueError('reversed start bracket')
    tick=integer(start_sample['machTicks'],1);numer=integer(start_sample['timebaseNumer'],1,2**32-1);denom=integer(start_sample['timebaseDenom'],1,2**32-1)
    budget=min(integer(scope_remaining_ns,1),360_000_000_000)
    if budget<=80_000_000_000:raise ValueError('insufficient one-case observation and cleanup reserve')
    # Start sampling precedes launching xcodebuild. The earlier host endpoint
    # is converted conservatively, rather than assuming the sample was instant.
    uncertainty=Fraction((after-before)*denom,numer)
    anchor=tick-(-(-uncertainty.numerator//uncertainty.denominator))
    if anchor<=0:raise ValueError('start anchor underflow')
    def cutoff(ns):
        result=anchor+(ns*denom//numer)
        if result>MAX_TICK:raise ValueError('budget tick overflow')
        return result
    observation=cutoff(budget-80_000_000_000)
    cleanup=cutoff(budget-10_000_000_000)
    outer=cutoff(budget)
    if not tick<observation<cleanup<outer:raise ValueError('budget exhausted by start uncertainty')
    return {'schema':'p1-direct-case-budget-v1','startSample':dict(start_sample),
            'scopeRemainingNs':scope_remaining_ns,'effectiveCommandBudgetNs':budget,
            'observationDeadlineMach':observation,'cleanupDeadlineMach':cleanup,
            'outerDeadlineMach':outer,'cleanupReserveNs':70_000_000_000,
            'parentReapingReserveNs':10_000_000_000,'nativeMethodAllowanceSeconds':240,
            'originalCommandAllowanceSeconds':360,'admissionEligible':False}
