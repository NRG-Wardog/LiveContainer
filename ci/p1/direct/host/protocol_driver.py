"""Original 29-request fixture protocol, with in-process Mach observations.

Transport is injected: the integrating collector must bind it to the exact
session/container and retain every request/response and event byte. This driver
never supplies a production action, a timing sleep, or a fabricated response.
"""
import math
from copy import deepcopy

PHASES = ('pre', 'mid', 'post')
MODEL = 'scenario-wide-constant-offset-and-unit-rate-conditional'


def require(value, message):
    if not value:
        raise ValueError(message)


class Driver:
    def __init__(self, *, identity, exchange, await_event, sample_mach, checkpoint, persist):
        self.identity = deepcopy(identity)
        self.exchange = exchange
        self.await_event = await_event
        self.sample_mach = sample_mach
        self.checkpoint = checkpoint
        self.persist = persist
        self.commands = []
        self.app = []
        self.mach = []
        self.events = []
        self.failed = False
        self.started = False
        self.finished = False

    def document(self):
        return {'schema': 'p1-direct-bound-clocks-v1', 'identity': deepcopy(self.identity),
                'appExchanges': deepcopy(self.app), 'machExchanges': deepcopy(self.mach),
                'model': MODEL, 'admissionEligible': False}

    def snapshot(self):
        return {'schema': 'p1-direct-protocol-driver-v1', 'clockDocument': self.document(),
                'commands': deepcopy(self.commands), 'events': deepcopy(self.events),
                'started': self.started, 'protocolComplete': self.finished,
                'failed': self.failed, 'admissionEligible': False}

    def save(self):
        self.persist(self.snapshot())

    def request(self, kind, expected_phase=None):
        self.checkpoint()
        sequence = len(self.commands) + 1
        row = self.exchange(sequence, kind)
        # Retain unsuccessful rows too, before validating. The transport must
        # independently persist if it raises before returning this receipt.
        self.commands.append(deepcopy(row))
        self.save()
        require(type(row) is dict and set(row) == {'id', 'kind', 'hostBeforeNs', 'hostAfterNs', 'response'}, 'exact exchange receipt')
        require(type(row['id']) is int and row['id'] == sequence and row['kind'] == kind, 'request identity')
        before, after = row['hostBeforeNs'], row['hostAfterNs']
        require(type(before) is int and type(after) is int and 0 <= before <= after, 'host bracket')
        require(after - before <= 5_000_000_000, 'original five-second response deadline')
        if len(self.commands) > 1:
            require(before >= self.commands[-2]['hostAfterNs'], 'host request chronology')
        response = row['response']
        keys = {'id', 'appReceive', 'appSend'} | ({'phase'} if kind != 'clock' else set())
        require(type(response) is dict and set(response) == keys, 'exact fixture response')
        require(type(response['id']) is int and response['id'] == sequence, 'response identity')
        for key in ('appReceive', 'appSend'):
            value = response[key]
            require(type(value) in (int, float) and math.isfinite(value) and value >= 0, 'native uptime')
        require(response['appSend'] >= response['appReceive'], 'app clock reversal')
        if expected_phase is not None:
            require(response['phase'] == expected_phase, 'fixture phase mismatch')
        self.checkpoint()
        return row

    def calibrate(self, phase):
        for ordinal in range(1, 9):
            self.checkpoint()
            mach = self.sample_mach(phase, ordinal)
            self.mach.append(deepcopy(mach))
            self.save()
            require(type(mach) is dict and mach.get('phase') == phase and mach.get('ordinal') == ordinal, 'Mach sample identity')
            row = self.request('clock')
            response = row['response']
            self.app.append({'phase': phase, 'ordinal': ordinal, 'requestID': row['id'],
                             'hostBeforeNs': row['hostBeforeNs'], 'hostAfterNs': row['hostAfterNs'],
                             'appReceive': response['appReceive'], 'appSend': response['appSend']})
            self.save()

    def event(self, kind, timeout=90):
        self.checkpoint()
        receipt = self.await_event(kind, timeout)
        self.events.append(deepcopy(receipt))
        self.save()
        require(type(receipt) is dict and receipt.get('type') == kind, 'event identity')
        self.checkpoint()

    def run(self):
        require(not self.started and not self.failed, 'driver is single-use')
        self.started = True
        try:
            self.save()
            self.event('start', 10)
            self.event('baseline-ready')
            self.calibrate('pre')
            self.request('ready', 'ready')
            self.event('window-end')
            self.request('mid', 'calibrating-mid')
            self.calibrate('mid')
            self.request('third', 'third-ready')
            self.event('post-ready')
            self.request('post', 'calibrating-post')
            self.calibrate('post')
            self.request('finish', 'finished')
            require(len(self.commands) == 29 and len(self.app) == len(self.mach) == 24, 'original inventory incomplete')
            self.finished = True
            self.save()
            return self.snapshot()
        except BaseException:
            self.failed = True
            self.finished = False
            # Persistence failure never turns a protocol failure into success.
            self.save()
            raise
