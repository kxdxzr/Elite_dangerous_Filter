"""Offline process-level checks of the individual agent entry points."""
import json
from pathlib import Path
import subprocess
import sys
import unittest


TOOLS = Path(__file__).resolve().parents[1] / 'src' / 'agent_tools'
NAMES = ('search_systems', 'search_stations', 'search_pve', 'search_hge',
         'search_engineer_shopping', 'search_full_outfitting', 'search_waypoint_route',
         'search_colonisation', 'search_rare_goods', 'search_midpoint',
         'resolve_system', 'read_current_system')


def call(name, data=None, *args):
    return subprocess.run([sys.executable, str(TOOLS / (name + '.py')), *args],
                          input=json.dumps(data) if data is not None else '',
                          capture_output=True, text=True, encoding='utf-8', timeout=30)


class AgentToolEntriesTests(unittest.TestCase):
    def test_each_entry_describes_its_own_operation(self):
        for name in NAMES:
            with self.subTest(name=name):
                process = call(name, None, '--describe')
                self.assertEqual(process.returncode, 0, process.stderr)
                response = json.loads(process.stdout)
                self.assertEqual(response['status'], 'ok')
                self.assertEqual(response['operation'], name)
                self.assertIsInstance(response['arguments'], dict)

    def test_simple_input_returns_structured_error(self):
        process = call('search_systems', {})
        self.assertEqual(process.returncode, 1)
        self.assertEqual(json.loads(process.stdout)['error']['code'], 'invalid_request')

    def test_envelope_preserves_request_id(self):
        process = call('search_systems', {'arguments': {}, 'request_id': 'test'})
        self.assertEqual(process.returncode, 1)
        self.assertEqual(json.loads(process.stdout)['request_id'], 'test')

    def test_bad_json_yields_one_error_object(self):
        process = subprocess.run([sys.executable, str(TOOLS / 'read_current_system.py')],
                                 input='not json', capture_output=True, text=True,
                                 encoding='utf-8', timeout=30)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(json.loads(process.stdout)['error']['code'], 'invalid_request')
