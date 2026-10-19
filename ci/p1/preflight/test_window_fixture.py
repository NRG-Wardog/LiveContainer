"""Portable design/packet tests; these do not compile or execute the Swift view."""
import hashlib
from pathlib import Path
import unittest

import window_packet as p
import window_fixture_route as route

HERE = Path(__file__).resolve().parent
SESSION = '00112233445566778899aabbccddeeff'


class PacketTests(unittest.TestCase):
    def test_fixed_packet_vector(self):
        self.assertEqual(p.packet_bytes(SESSION, 1).hex(),
                         '503157430100112233445566778899aabbccddeeff00000001000000f2a4d7a0')

    def test_nonce_is_all_sixteen_bytes(self):
        self.assertEqual(p.packet_bytes(SESSION, 1)[5:21], bytes.fromhex(SESSION))

    def test_packet_lengths_and_reserved(self):
        packet = p.packet_bytes(SESSION, 1)
        self.assertEqual(len(packet), 32)
        self.assertEqual(packet[:5], b'P1WC\x01')
        self.assertEqual(packet[21:28], b'\0\0\0\x01\0\0\0')

    def test_all_bounded_markers_roundtrip(self):
        for marker in range(1, p.MAXIMUM_MARKER + 1):
            value = p.decode_samples(p.grid(p.packet_bytes(SESSION, marker)), SESSION)
            self.assertEqual(value['marker'], marker)
            self.assertEqual(value['session'], SESSION)
            self.assertFalse(value['admissionEligible'])
            self.assertFalse(value['feedback_lifetime_established'])
            self.assertFalse(value['input_overlap_established'])
            self.assertFalse(value['timestampUnitsEstablished'])

    def test_each_nonce_bit_is_preserved(self):
        for index in range(128):
            session = (1 << index).to_bytes(16, 'big').hex()
            self.assertEqual(p.decode_samples(p.grid(p.packet_bytes(session, 1)), session)['session'], session)

    def test_session_rejects_missing_truncated_uppercase_and_extra(self):
        for value in ('', SESSION[:-1], SESSION.upper(), SESSION + '0', 'g' * 32, None, SESSION + '\n'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                p.nonce_bytes(value)

    def test_markers_do_not_wrap_or_accept_bool(self):
        for marker in (0, -1, 3601, 2**32, True, 1.0):
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                p.packet_bytes(SESSION, marker)

    def test_wrong_session_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'session mismatch'):
            p.decode_samples(p.grid(p.packet_bytes(SESSION, 1)), 'f' * 32)

    def test_ambiguous_sample_is_rejected(self):
        cells = p.grid(p.packet_bytes(SESSION, 1)); cells[3][3] = 128
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            p.decode_samples(cells, SESSION)

    def test_nonfinite_sample_is_rejected(self):
        cells = p.grid(p.packet_bytes(SESSION, 1)); cells[3][3] = float('nan')
        with self.assertRaisesRegex(ValueError, 'invalid sample'):
            p.decode_samples(cells, SESSION)

    def test_single_rail_damage_is_rejected(self):
        cells = p.grid(p.packet_bytes(SESSION, 1)); cells[3][3] = cells[3][4]
        with self.assertRaisesRegex(ValueError, 'complementary'):
            p.decode_samples(cells, SESSION)

    def test_complementary_corruption_is_rejected_by_crc(self):
        cells = p.grid(p.packet_bytes(SESSION, 1)); cells[7][3:5] = cells[7][3:5][::-1]
        with self.assertRaisesRegex(ValueError, 'checksum'):
            p.decode_samples(cells, SESSION)

    def test_torn_packets_are_rejected(self):
        a = p.grid(p.packet_bytes(SESSION, 1)); b = p.grid(p.packet_bytes('f' * 32, 2))
        with self.assertRaises(ValueError):
            p.decode_samples(a[:11] + b[11:], SESSION)

    def test_missing_geometry_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'geometry'):
            p.decode_samples(p.grid(p.packet_bytes(SESSION, 1))[:-1], SESSION)

    def test_quiet_zone_and_registration_damage_are_rejected(self):
        for y, x in ((0, 0), (1, 1), (2, 2), (20, 10), (21, 37)):
            cells = p.grid(p.packet_bytes(SESSION, 1)); cells[y][x] = 255 - cells[y][x]
            with self.subTest(x=x, y=y), self.assertRaisesRegex(ValueError, 'quiet-zone'):
                p.decode_samples(cells, SESSION)

    def test_rotated_board_is_not_silently_reoriented(self):
        cells = p.grid(p.packet_bytes(SESSION, 1))
        with self.assertRaises(ValueError):
            p.decode_samples([row[::-1] for row in cells[::-1]], SESSION)

    def test_blank_board_is_rejected(self):
        with self.assertRaises(ValueError):
            p.decode_samples([[255] * p.COLUMNS for _ in range(p.ROWS)], SESSION)


class SourceProposalTests(unittest.TestCase):
    def test_base_matches_reviewed_hash(self):
        self.assertEqual(hashlib.sha256(route.BASE.read_bytes()).hexdigest(), route.BASE_SHA256)

    def test_route_changes_only_initializer_and_branch(self):
        base = route.BASE.read_text(); candidate = route.proposed_source(base)
        reverted = candidate.replace(route.NEW_INIT, route.OLD_INIT).replace(route.NEW_ROUTE, route.OLD_ROUTE)
        self.assertEqual(reverted, base)
        self.assertIn('else { P1VideoPromptScreen() }', candidate)
        self.assertIn('else if ProcessInfo.processInfo.arguments.contains("--recovery")', candidate)

    def test_drift_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'source drift'):
            route.proposed_source(route.BASE.read_text() + '\n')

    def test_fixture_has_no_production_actions_or_capture_api(self):
        source = (HERE / 'window_fixture.swift').read_text()
        for token in ('UIPasteboard', 'V3PromptSection', 'copyDiagnostic', 'Task.sleep', 'SCStream',
                      'CGRequestScreenCaptureAccess', 'URLSession', '@main'):
            self.assertNotIn(token, source)

    def test_source_has_nonce_draw_and_shutdown_guards(self):
        source = (HERE / 'window_fixture.swift').read_text()
        for token in ('session.utf8.count == 32', 'nonce.count == 16',
                      'marker += 1', 'maximumMarker: UInt32 = 3600',
                      'ProcessInfo.processInfo.systemUptime - start < 120',
                      'link?.invalidate()', 'view.stop()', '0xEDB88320', 'packet.count == 32'):
            self.assertIn(token, source)
        self.assertIn('arguments.filter({ $0 == "--session" }).count == 1', source)
        self.assertIn('arguments.filter({ $0 == "--window-capture-fixture" }).count == 1', source)

    def test_readiness_is_one_time_after_paint_and_session_exclusive(self):
        source = (HERE / 'window_fixture.swift').read_text()
        self.assertIn('if !readinessAttempted {', source)
        self.assertIn('readinessAttempted = true', source)
        self.assertGreater(source.index('if !readinessAttempted {'), source.index('let drawAfter ='))
        for token in ('DispatchQueue.main.async {', 'DispatchQueue.global(qos: .utility).async {',
                      '.appendingPathComponent("p1-window", isDirectory: true)',
                      'mkdirat(parent, session, 0o700) == 0', 'O_EXCL | O_NOFOLLOW',
                      'renameat(directory, ".ready.tmp", directory, "ready.json")',
                      '"schema": "p1-window-fixture-ready-v1"', '"displayTimeEstablished": false'):
            self.assertIn(token, source)


if __name__ == '__main__':
    unittest.main()
