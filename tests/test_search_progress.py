import unittest
from unittest.mock import Mock

from search_progress import measure, SearchProgress, OverallEstimate
from i18n import translate, message


class ProgressTests(unittest.TestCase):
    def test_overall_and_stage_are_both_visible_and_localized(self):
        bar, label, localizer = Mock(), Mock(), Mock(language='en')
        localizer.tr.side_effect = lambda s: translate(s, 'en')
        localizer.message.side_effect = lambda key, **values: message(key, 'en', **values)
        tracker = SearchProgress(bar, label, localizer)
        tracker.begin()
        tracker.update('', dict(done=2, work_total=8, stage='天体批次', overall=dict(
            scanned=500, total=800, hits=4, want=50, page=2, step=3, steps=5)))
        text = label.set.call_args.args[0]
        self.assertIn('Overall: page 2', text)
        self.assertIn('500/800', text)
        self.assertIn('4/50', text)
        self.assertIn('3/5', text)
        self.assertIn('Body batches: 2/8', text)
        self.assertIn('Elapsed', text)
        tracker.finish(False)
        self.assertIn('Paused / ended', label.set.call_args.args[0])
        bar.after_cancel.assert_called()

    def test_eta_requires_samples_and_unknown_totals_are_not_invented(self):
        now = [0.0]
        estimate = OverallEstimate(lambda: now[0])
        estimate.begin()
        for seconds, scanned in ((5, 50), (10, 100), (15, 150)):
            now[0] = seconds
            estimate.update(dict(scanned=scanned, total=500, hits=0, want=20))
        lo, hi = estimate.remaining()
        self.assertLessEqual(lo, 35)
        self.assertGreaterEqual(hi, 35)
        estimate.work['total'] = 10000
        self.assertIsNone(estimate.remaining())
        estimate.work['total'] = None
        self.assertIsNone(estimate.remaining())

    def test_target_eta_pause_time_and_resumed_replay(self):
        now = [0.0]
        estimate = OverallEstimate(lambda: now[0])
        estimate.begin()
        for seconds, scanned, hits in ((5, 50, 2), (10, 100, 4), (15, 150, 6)):
            now[0] = seconds
            estimate.update(dict(scanned=scanned, total=10000, hits=hits, want=12))
        self.assertIsNotNone(estimate.remaining())
        estimate.pause()
        now[0] = 1000
        self.assertEqual(estimate.seconds(), 15)
        self.assertIsNone(estimate.remaining())
        estimate.begin(continuing=True)
        estimate.update(dict(scanned=50, total=10000, hits=2, want=12))
        self.assertEqual(estimate.work['scanned'], 150)
        self.assertEqual(estimate.work['hits'], 6)
        self.assertIsNone(estimate.remaining())
        now[0] += 5
        self.assertEqual(estimate.seconds(), 20)
        estimate.begin()
        self.assertEqual(estimate.work, {})
        self.assertEqual(estimate.seconds(), 0)

    def test_long_stall_hides_previously_valid_eta(self):
        now = [0.0]
        estimate = OverallEstimate(lambda: now[0])
        estimate.begin()
        for seconds, scanned in ((5, 50), (10, 100), (15, 150)):
            now[0] = seconds
            estimate.update(dict(scanned=scanned, total=500, hits=0))
        self.assertIsNotNone(estimate.remaining())
        now[0] = 100
        self.assertIsNone(estimate.remaining())

    def test_unknown_total_uses_static_count_not_bouncing_animation(self):
        bar, label, localizer = Mock(), Mock(), Mock(language='en')
        localizer.tr.side_effect = lambda s: translate(s, 'en')
        localizer.message.side_effect = lambda key, **values: message(key, 'en', **values)
        tracker = SearchProgress(bar, label, localizer)
        tracker.update('RES 星系分页：2；已读取 1000 个星系')
        self.assertEqual(bar.configure.call_args.kwargs['mode'], 'determinate')
        self.assertIn('1,000', label.set.call_args.args[0])
        self.assertIn('total unknown', label.set.call_args.args[0])
        bar.start.assert_not_called()

    def test_source_annotation_reports_real_stage_progress(self):
        self.assertEqual(measure('任务来源控制派系：2/8'), (2, 8, '来源控制派系'))
    def test_known_work_ignores_arbitrary_page_budget(self):
        self.assertEqual(measure('', dict(scanned=500, total=800, pages=1, per=500)),
                         (500, 800, '候选核查'))

    def test_capped_or_unknown_server_count_has_no_percentage(self):
        for total in (0, None, 10000, 10001):
            self.assertIsNone(measure('', dict(scanned=500, total=total))[1])

    def test_known_stage_counts_even_above_server_cap(self):
        self.assertEqual(measure('', dict(done=350, work_total=28000, stage='候选核查')),
                         (350, 28000, '候选核查'))
        for message, expected in [('查询派系详情：3/8 个星系', (3, 8)),
                                  ('Checking 350/800: A → B', (350, 800)),
                                  ('Body batches 3/10; matches 2', (3, 10)),
                                  ('查询目标星环距离：4/12', (4, 12))]:
            self.assertEqual(measure(message)[:2], expected)

    def test_fetch_does_not_hide_known_candidate_coverage(self):
        bar, label, localizer = Mock(), Mock(), Mock(language='en')
        localizer.tr.side_effect = lambda s: translate(s, 'en')
        localizer.message.side_effect = lambda key, **values: message(key, 'en', **values)
        tracker = SearchProgress(bar, label, localizer)
        tracker.update('', dict(phase='fetch', scanned=350, total=800))
        self.assertEqual(bar.configure.call_args.kwargs['value'], 43.75)
        self.assertIn('350/800', label.set.call_args.args[0])
        tracker.finish(False)
        self.assertIn('incomplete', label.set.call_args.args[0])
        tracker.finish(True)
        self.assertEqual(bar.configure.call_args.kwargs['value'], 100)
