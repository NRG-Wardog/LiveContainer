"""Fail-closed admission of passive samples of the real production AX label."""
import math

IDENTIFIER = 'signin.prompt.copy-details'


def require(ok, message):
    if not ok: raise ValueError(message)


def number(value):
    return type(value) in (float, int) and math.isfinite(value)


def rectangle(value):
    return isinstance(value, list) and len(value) == 4 and all(number(x) for x in value) and value[2] > 0 and value[3] > 0


def label(sample, expected):
    if not (sample.get('matchCount') == 1 and sample.get('label') == expected and
            sample.get('identifier') == IDENTIFIER and sample.get('shown') is True and
            rectangle(sample.get('frame')) and rectangle(sample.get('viewport'))): return False
    x, y, w, h = sample['frame']; vx, vy, vw, vh = sample['viewport']
    return x >= vx - 1 and y >= vy - 1 and x + w <= vx + vw + 1 and y + h <= vy + vh + 1


def verify(trace, scenario, phase, ordinals, overlap):
    require(isinstance(trace, dict) and trace.get('schema') == 'p1-passive-ax-trace-v1' and
            trace.get('scenario') == scenario and trace.get('phase') == phase and
            trace.get('source') == 'public UIKit accessibility tree; production identifier/label/frame', 'wrong passive AX identity')
    events, samples = trace.get('events', []), trace.get('samples', [])
    require(isinstance(events, list) and [e.get('ordinal') for e in events] == ordinals and
            all(type(e.get('ordinal')) is int and type(e.get('changeCount')) is int and
                e['changeCount'] >= 0 and e.get('clipboardExact') is True and e.get('shown') is True for e in events),
            'wrong exact clipboard event ordinals')
    require(len({e['changeCount'] for e in events}) == len(events) and
            all(a['changeCount'] < b['changeCount'] for a, b in zip(events, events[1:])), 'clipboard events not distinct')
    expected_drivers = ['XCTest-tap', 'public-accessibilityActivate'] if overlap else ['XCTest-tap']
    require([e.get('driver') for e in events] == expected_drivers, 'wrong actual input drivers')
    require(all(number(e.get('time')) for e in events) and events[0]['time'] == 0 and
            all(a['time'] < b['time'] for a, b in zip(events, events[1:])), 'invalid clipboard event times')
    require(isinstance(samples, list) and 10 < len(samples) <= 160 and
            trace.get('sampleIntervalSeconds') == 0.05 and number(trace.get('duration')) and
            0 < trace['duration'] <= 7.5, 'invalid passive sample bound')
    require(all(number(s.get('time')) and 0 <= s['time'] <= trace['duration'] and
                s.get('identifier') == IDENTIFIER and type(s.get('matchCount')) is int and
                0 <= s['matchCount'] <= 1 and s.get('traversalExhausted') is False and
                type(s.get('shown')) is bool and type(s.get('generation')) is int for s in samples) and
            all(a['time'] < b['time'] for a, b in zip(samples, samples[1:])), 'unavailable/ambiguous passive AX hierarchy')
    start = events[-1]['time']
    late = next((s for s in samples if label(s, 'Copied') and 1.5 <= s['time'] - start < 3), None)
    require(late is not None, 'actual rendered Copied minimum lifetime unobserved')
    expiry = next((s for s in samples if label(s, 'Copy Details') and late['time'] < s['time'] and s['time'] - start < 5), None)
    require(expiry is not None, 'actual rendered feedback expiry unobserved')
    result = {'minimumLifetimeSeconds': late['time'] - start, 'feedbackObservedSeconds': late['time'] - start,
              'observedExpirySeconds': expiry['time'] - start}
    transitions, activations = trace.get('transitions'), trace.get('activations')
    if not overlap:
        require(transitions == [] and activations == [], 'normal XCTest tap replaced by fixture activation')
        return result
    spacing = start - events[0]['time']
    require(0.75 <= spacing < 2 and late['time'] - events[0]['time'] >= 2.25, 'own lifetime does not cross old timer deadline')
    kinds = ['replace'] if scenario == 'prompt-replacement' else ['dismiss', 'reopen']
    require(isinstance(transitions, list) and [t.get('kind') for t in transitions] == kinds and
            all(number(t.get('time')) and 0 < t['time'] < start for t in transitions) and
            all(a['time'] < b['time'] for a, b in zip(transitions, transitions[1:])), 'invalid lifecycle transition times')
    transition = transitions[0]['time']
    require(transition < 2 and any(label(s, 'Copied') and s['time'] < transition for s in samples), 'original Copied not observed before transition')
    require(any(label(s, 'Copy Details') and transitions[-1]['time'] <= s['time'] < start for s in samples),
            'actual replacement/reopened feedback reset unobserved')
    require(isinstance(activations, list) and len(activations) == 1 and activations[0].get('success') is True and
            activations[0].get('identifier') == IDENTIFIER and activations[0].get('labelBefore') == 'Copy Details' and
            number(activations[0].get('time')) and transitions[-1]['time'] <= activations[0]['time'] <= start,
            'actual production AX activation not proven')
    require([e.get('generation') for e in events] == ([0, 1] if scenario == 'prompt-replacement' else [0, 0]),
            'wrong prompt generation transition')
    if scenario == 'dismiss-reopen':
        require(any(s['shown'] is False and s['matchCount'] == 0 and
                    transition <= s['time'] <= transitions[1]['time'] for s in samples), 'actual dismissed element absence unobserved')
    result.update(transitionDelaySeconds=transition, copyEventSpacingSeconds=spacing)
    return result


def verify_observations(observations, scenario):
    overlap = scenario != 'feedback-timeout'
    first = verify(observations.get('passiveTrace'), scenario, 'overlap', [1, 2] if overlap else [1], overlap)
    for key, value in first.items():
        require(number(observations.get(key)) and math.isclose(observations[key], value, abs_tol=1e-6), 'summary disagrees with actual passive trace')
    if overlap:
        normal = observations.get('normalTapObservation', {})
        last = verify(normal.get('passiveTrace'), scenario, 'normal-xctest-tap', [3], False)
        for key, value in last.items():
            require(number(normal.get(key)) and math.isclose(normal[key], value, abs_tol=1e-6), 'normal tap summary differs')
        require(normal['passiveTrace']['events'][0]['changeCount'] > observations['passiveTrace']['events'][-1]['changeCount'] and
                observations.get('inputDrivers') == ['XCTest-tap', 'public-accessibilityActivate', 'XCTest-tap'],
                'separate replacement XCTest tap not proven')
    return first
