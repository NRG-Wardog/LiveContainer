"""Synthetic verifier unit inputs; these are never native/UI evidence."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('trace_verifier', Path(__file__).resolve().parents[1] / 'feedback_trace.py')
trace = importlib.util.module_from_spec(spec); spec.loader.exec_module(trace)


def sample_trace(scenario='prompt-replacement', normal=False):
    overlap = scenario != 'feedback-timeout' and not normal
    events = [{'ordinal': 3 if normal else 1, 'time': 0, 'generation': 1 if normal and scenario == 'prompt-replacement' else 0,
               'shown': True, 'clipboardExact': True, 'changeCount': 13 if normal else 11, 'driver': 'XCTest-tap'}]
    if overlap: events.append({'ordinal': 2, 'time': 1.1, 'generation': 1 if scenario == 'prompt-replacement' else 0,
        'shown': True, 'clipboardExact': True, 'changeCount': 12, 'driver': 'public-accessibilityActivate'})
    samples = []
    for i in range(1, 85 if overlap else 63):
        t = round(i * .05, 2); shown = not (overlap and scenario == 'dismiss-reopen' and .75 <= t < .9)
        copied = (.0 < t < .75 or 1.1 <= t < 3.1) if overlap else t < 2
        samples.append({'time': t, 'identifier': trace.IDENTIFIER, 'generation': 1 if scenario == 'prompt-replacement' and (normal or t >= .75) else 0,
            'shown': shown, 'matchCount': 1 if shown else 0, 'traversalExhausted': False,
            'label': ('Copied' if copied else 'Copy Details') if shown else '',
            'frame': [10, 10, 90, 44] if shown else [0, 0, 0, 0], 'viewport': [0, 0, 400, 800]})
    transitions = [{'kind': 'replace' if scenario == 'prompt-replacement' else 'dismiss', 'time': .75}] if overlap else []
    if overlap and scenario == 'dismiss-reopen': transitions.append({'kind': 'reopen', 'time': .9})
    return {'schema': 'p1-passive-ax-trace-v1', 'scenario': scenario,
        'phase': 'normal-xctest-tap' if normal else 'overlap', 'duration': 4.2 if overlap else 3.1,
        'sampleIntervalSeconds': .05, 'source': 'public UIKit accessibility tree; production identifier/label/frame',
        'events': events, 'samples': samples, 'transitions': transitions,
        'activations': [{'time': 1.05, 'success': True, 'identifier': trace.IDENTIFIER, 'labelBefore': 'Copy Details'}] if overlap else []}


def observations(scenario):
    overlap = scenario != 'feedback-timeout'; first = sample_trace(scenario)
    result = dict(trace.verify(first, scenario, 'overlap', [1, 2] if overlap else [1], overlap), passiveTrace=first)
    if overlap:
        normal = sample_trace(scenario, True)
        result['normalTapObservation'] = dict(trace.verify(normal, scenario, 'normal-xctest-tap', [3], False), passiveTrace=normal)
        result['inputDrivers'] = ['XCTest-tap', 'public-accessibilityActivate', 'XCTest-tap']
    return result


class FeedbackTraceTests(unittest.TestCase):
    def test_accepts_exact_three_scenarios(self):
        for name in ['feedback-timeout', 'prompt-replacement', 'dismiss-reopen']:
            with self.subTest(name=name): trace.verify_observations(observations(name), name)

    def reject(self, mutate, scenario='prompt-replacement'):
        value = observations(scenario); mutate(value)
        with self.assertRaises(ValueError): trace.verify_observations(value, scenario)

    def test_rejects_expected_state_without_actual_label(self):
        self.reject(lambda o: [s.update(label='') for s in o['passiveTrace']['samples']])

    def test_rejects_missing_trace(self): self.reject(lambda o: o.pop('passiveTrace'))
    def test_rejects_wrong_identifier(self):
        self.reject(lambda o: [s.update(identifier='fixture-copy') for s in o['passiveTrace']['samples']])
    def test_rejects_ambiguous_actual_element(self):
        self.reject(lambda o: o['passiveTrace']['samples'][0].update(matchCount=2))
    def test_rejects_exhausted_hierarchy(self):
        self.reject(lambda o: o['passiveTrace']['samples'][0].update(traversalExhausted=True))
    def test_rejects_invisible_label_frames(self):
        self.reject(lambda o: [s.update(frame=[0, 0, 0, 0]) for s in o['passiveTrace']['samples']])
    def test_rejects_offscreen_label_frames(self):
        self.reject(lambda o: [s.update(frame=[0, 900, 90, 44]) for s in o['passiveTrace']['samples']])
    def test_rejects_nonfinite_times(self):
        self.reject(lambda o: o['passiveTrace']['samples'][0].update(time=float('nan')))
    def test_rejects_duplicate_timestamps(self):
        self.reject(lambda o: o['passiveTrace']['samples'][1].update(time=.05))
    def test_rejects_reused_pasteboard_change(self):
        self.reject(lambda o: o['passiveTrace']['events'][1].update(changeCount=11))
    def test_rejects_activation_without_event(self):
        self.reject(lambda o: o['passiveTrace']['events'].pop())
    def test_rejects_failed_activation(self):
        self.reject(lambda o: o['passiveTrace']['activations'][0].update(success=False))
    def test_rejects_unobserved_first_feedback(self):
        self.reject(lambda o: [s.update(label='Copy Details') for s in o['passiveTrace']['samples'] if s['time'] < .75])
    def test_rejects_unobserved_reset(self):
        self.reject(lambda o: [s.update(label='Copied') for s in o['passiveTrace']['samples'] if .75 <= s['time'] < 1.1])
    def test_rejects_unobserved_dismissal(self):
        self.reject(lambda o: [s.update(shown=True, matchCount=1) for s in o['passiveTrace']['samples']], 'dismiss-reopen')
    def test_rejects_premature_own_lifetime(self):
        self.reject(lambda o: [s.update(label='Copy Details') for s in o['passiveTrace']['samples'] if s['time'] >= 2.5])
    def test_rejects_missing_expiry(self):
        self.reject(lambda o: [s.update(label='Copied') for s in o['passiveTrace']['samples'] if s['time'] >= 3.1])
    def test_rejects_summary_without_measurements(self):
        self.reject(lambda o: o.update(minimumLifetimeSeconds=1.8))
    def test_rejects_third_event_satisfying_overlap(self):
        self.reject(lambda o: o['passiveTrace']['events'][1].update(ordinal=3))
    def test_rejects_missing_normal_xctest_tap(self):
        self.reject(lambda o: o.pop('normalTapObservation'))
    def test_rejects_assisted_normal_tap(self):
        self.reject(lambda o: o['normalTapObservation']['passiveTrace']['events'][0].update(driver='public-accessibilityActivate'))
    def test_rejects_third_clipboard_reuse(self):
        self.reject(lambda o: o['normalTapObservation']['passiveTrace']['events'][0].update(changeCount=12))
    def test_rejects_unbounded_samples(self):
        self.reject(lambda o: o['passiveTrace']['samples'].extend(copy.deepcopy(o['passiveTrace']['samples'])))


if __name__ == '__main__': unittest.main()
