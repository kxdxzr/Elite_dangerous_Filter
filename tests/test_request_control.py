import io
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import filter_engine as eng
import request_control


def gateway(headers=None):
    return HTTPError('https://spansh.co.uk/api/systems/search', 502, 'Bad Gateway', headers or {}, None)


class RequestControlTests(unittest.TestCase):
    def controller(self):
        now = [0.0]
        def sleep(delay):
            now[0] += delay
        return request_control.RequestControl(clock=lambda: now[0], sleep=sleep, jitter=lambda: 0,
                                             wall_clock=lambda: 1000), now

    def test_bounded_retries_and_shared_cooldown(self):
        control, now = self.controller()
        operation = Mock(side_effect=[gateway(), gateway(), {'ok': True}])
        self.assertEqual(control.run(operation), {'ok': True})
        self.assertEqual(operation.call_count, 3)
        self.assertGreaterEqual(now[0], 4.5)
        broken = Mock(side_effect=gateway())
        with self.assertRaises(HTTPError) as error:
            control.run(broken)
        self.assertTrue(error.exception.elite_retry_exhausted)
        self.assertEqual(broken.call_count, 3)
        until = control.cooldown
        control.run(lambda: True)
        self.assertGreaterEqual(now[0], until)

    def test_retry_after_long_delay_pauses_instead_of_retrying_early(self):
        for header in ('20', 'Thu, 01 Jan 1970 00:17:00 GMT'):
            control, now = self.controller()
            operation = Mock(side_effect=gateway({'Retry-After': header}))
            with self.assertRaises(HTTPError):
                control.run(operation)
            self.assertEqual(operation.call_count, 1)
            self.assertEqual(control.cooldown, 20)
            self.assertEqual(now[0], 0)

    def test_non_transient_and_invalid_json_are_not_retried(self):
        control, _ = self.controller()
        for error in (HTTPError('url', 403, 'Forbidden', {}, None), ValueError('invalid schema')):
            operation = Mock(side_effect=error)
            with self.assertRaises(type(error)):
                control.run(operation)
            self.assertEqual(operation.call_count, 1)

    def test_stop_interrupts_cooldown(self):
        control, _ = self.controller()
        stop = threading.Event()
        operation = Mock(side_effect=gateway())
        with self.assertRaises(InterruptedError):
            control.run(operation, stop, lambda text: stop.set())
        self.assertEqual(operation.call_count, 1)

    def test_global_request_concurrency_is_two_not_two_per_tool(self):
        control = request_control.RequestControl(interval=0)
        lock, barrier = threading.Lock(), threading.Barrier(2)
        active, peak, results = [0], [0], []
        def operation():
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            barrier.wait(timeout=5)
            with lock:
                active[0] -= 1
            return True
        threads = [threading.Thread(target=lambda: results.append(control.run(operation))) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=8)
        self.assertEqual(peak[0], 2)
        self.assertEqual(results, [True] * 6)

    def test_only_spansh_api_is_governed(self):
        operation = Mock(return_value={})
        with patch.object(request_control, 'shared') as shared:
            request_control.request('https://www.edsm.net/api-v1/system', operation)
            request_control.request('https://spansh.co.uk.example.test/api/systems/search', operation)
            shared.run.assert_not_called()
            request_control.request('https://spansh.co.uk/api/systems/search', operation)
            shared.run.assert_called_once()

    def test_shared_transport_recovers_actual_http_502(self):
        control, _ = self.controller()
        response = io.BytesIO(b'{"results": []}')
        response.headers = {}
        with patch.object(request_control, 'shared', control), \
                patch.object(eng.urllib.request, 'urlopen', side_effect=[gateway(), response]) as http:
            self.assertEqual(eng._http_json('https://spansh.co.uk/api/systems/search', {}), {'results': []})
            self.assertEqual(http.call_count, 2)

    def test_stop_during_retry_retains_search_checkpoint(self):
        control, _ = self.controller()
        control.interval = 0
        state, stop = {}, threading.Event()
        response = io.BytesIO(b'{"count": 2, "results": [{"name": "A", "id64": 1}]}')
        response.headers = {}
        def progress(text, detail=None):
            if '冷却' in text:
                stop.set()
        with patch.object(request_control, 'shared', control), \
                patch.object(eng.urllib.request, 'urlopen', side_effect=[response, gateway()]):
            rows, _, _ = eng.search('systems', [], want=2, page_size=1, stop=stop, progress=progress, resume=state)
        self.assertEqual([r['name'] for r in rows], ['A'])
        self.assertTrue(state['paused'])

    def test_full_outfitting_does_not_multiply_exhausted_retries(self):
        import full_outfitting
        error = gateway()
        error.elite_retry_exhausted = True
        with patch.object(eng, '_http_json', side_effect=error) as http:
            with self.assertRaises(HTTPError):
                full_outfitting.request_json('https://spansh.co.uk/api/stations/search', {})
            http.assert_called_once()

    def test_reference_failure_is_not_misreported_as_unknown_system(self):
        error = gateway()
        error.elite_retry_exhausted = True
        with patch.object(eng, '_http_json', side_effect=[{}, error]), \
                patch.object(eng.fo, 'similar_systems') as suggest:
            with self.assertRaises(HTTPError):
                eng._lookup_exact('Reference')
            suggest.assert_not_called()
        with patch.object(eng, '_http_json', side_effect=InterruptedError('cancelled')):
            with self.assertRaises(InterruptedError):
                eng._lookup_exact('Reference')

    def test_field_suggestions_share_the_same_governor(self):
        import field_options
        with patch.object(request_control, 'request', return_value={'values': []}) as governed:
            self.assertEqual(field_options._http_json('https://spansh.co.uk/api/systems/field_values/name'), {'values': []})
            governed.assert_called_once()
