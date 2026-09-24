"""Pure model tests, without pretending to boot Home Assistant."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType('empower_test_model')
pkg.__path__ = [str(ROOT / 'custom_components/empower_naperville')]
sys.modules[pkg.__name__] = pkg
from empower_test_model.model import InvalidSnapshot, normalize, prepare, hourly_statistics, first_utc


def sample(start='2025-06-05T00:15:00', values=None):
    return {'version': 1, 'readsStartDate': start, 'deliveredReads': values if values is not None else [1, 2, 3, 4, 5, 6, 7, 8]}


class ModelTests(unittest.TestCase):
    def test_string_array_equivalence_and_field_whitelist(self):
        payload = sample(values='1, 2,3,4,5,6,7,8')
        payload['custId'] = 'synthetic-private'
        self.assertEqual(normalize(payload), normalize(sample()))
        self.assertNotIn('synthetic-private', str(normalize(payload)))

    def test_end_label_complete_hour_and_idempotence(self):
        data = normalize(sample())
        rows = hourly_statistics(data, 'America/Chicago', 'end')
        self.assertEqual(rows, hourly_statistics(data, 'America/Chicago', 'end'))
        self.assertEqual(rows[0]['start'].isoformat(), '2025-06-05T05:00:00+00:00')
        self.assertEqual([r['state'] for r in rows], [10, 26])
        self.assertEqual([r['sum'] for r in rows], [10, 36])

    def test_start_label_drops_partial_hours(self):
        rows = hourly_statistics(normalize(sample()), 'America/Chicago', 'start')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['state'], 22)
        self.assertEqual(rows[0]['start'].hour, 6)

    def test_append_and_correction_recompute(self):
        old = normalize(sample())
        new, _ = prepare(sample(values=[2,2,3,4,5,6,7,8,9,10,11,12]), 'America/Chicago', 'end', old)
        rows = hourly_statistics(new, 'America/Chicago', 'end')
        self.assertEqual(rows[-1]['sum'], 79)
        self.assertEqual(rows[0]['sum'], 11)

    def test_truncation_or_shift_rejected(self):
        old = normalize(sample())
        for new in (sample(values=[1]), sample(start='2025-06-06T00:15:00')):
            with self.assertRaises(InvalidSnapshot):
                prepare(new, 'America/Chicago', 'end', old)

    def test_invalid_intervals(self):
        for values in ('1,,2', '1,', '', [True], [None], [-1], [float('nan')], ['1'], [10**1000]):
            with self.subTest(values=values), self.assertRaises(InvalidSnapshot):
                normalize(sample(values=values))

    def test_ambiguous_and_nonexistent_dst_start(self):
        for start in ('2025-11-02T01:15:00', '2025-03-09T02:15:00'):
            with self.assertRaises(InvalidSnapshot):
                first_utc(start, 'America/Chicago')
        self.assertEqual(first_utc('2025-11-02T01:15:00-05:00', 'America/Chicago').hour, 6)

    def test_elapsed_intervals_across_dst(self):
        data = normalize(sample('2025-11-02T00:00:00', [1]*16))
        rows = hourly_statistics(data, 'America/Chicago', 'start')
        self.assertEqual([r['start'].hour for r in rows], [5,6,7,8])
        self.assertEqual(rows[-1]['sum'], 16)

    def test_invalid_timestamp_and_future(self):
        with self.assertRaises(InvalidSnapshot):
            normalize(sample('2025-06-05T00:16:00'))
        with self.assertRaises(InvalidSnapshot):
            prepare(sample(), 'America/Chicago', 'end', now=datetime(2020,1,1,tzinfo=timezone.utc))

    def test_snapshot_summary(self):
        _, summary = prepare(sample(), 'America/Chicago', 'end')
        self.assertEqual(summary['count'], 8)
        self.assertEqual(summary['total_kwh'], 36)
        self.assertEqual(summary['latest'], '2025-06-05T07:00:00+00:00')
