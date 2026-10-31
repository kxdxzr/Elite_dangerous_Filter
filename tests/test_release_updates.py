import copy
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import release_updates as updates


class ReleaseUpdatesTests(unittest.TestCase):
    def test_only_packaged_interactive_launch_auto_checks(self):
        self.assertFalse(updates.should_auto_check(False, ['filter_gui.py']))
        self.assertTrue(updates.should_auto_check(True, ['EliteDangerousFilter.exe']))
        for flag in ('--smoke-test', '--session-test'):
            self.assertFalse(updates.should_auto_check(True, ['EliteDangerousFilter.exe', flag]))

    def release(self, tag='v0.1.5'):
        return dict(tag_name=tag, draft=False, prerelease=False, assets=[dict(
            name='EliteDangerousFilter.exe', state='uploaded', size=100,
            browser_download_url=f'{updates.PROJECT_URL}/releases/download/{tag}/EliteDangerousFilter.exe')])

    def check(self, data, current='0.1.4-r1'):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps(data).encode()
        with patch.object(updates, 'urlopen', return_value=response) as http:
            result = updates.check_latest(current)
        self.assertEqual(http.call_count, 1)
        request = http.call_args.args[0]
        self.assertEqual(request.full_url, updates.LATEST_API)
        self.assertEqual(http.call_args.kwargs['timeout'], 12)
        response.read.assert_called_once_with(updates.MAX_RESPONSE + 1)
        self.assertIsNone(request.get_header('Authorization'))
        return result

    def test_numeric_versions_and_project_revision_order(self):
        sequence = ['0.1.4-beta.1', 'v0.1.4', '0.1.4-r1', '0.1.4-r2', '0.1.4-r10', '0.1.5', '0.1.10', '1.0.0']
        self.assertEqual(sorted(sequence, key=updates.version_key), sequence)
        self.assertEqual(updates.version_key('v0.1.4-r1+build'), updates.version_key('0.1.4-r1'))
        for value in (None, '', 'vNext', '1.2', '1.2.3/evil'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                updates.version_key(value)

    def test_newer_same_older_draft_and_prerelease(self):
        latest = self.check(self.release())
        self.assertEqual(latest.version, 'v0.1.5')
        self.assertEqual(latest.page_url, updates.PROJECT_URL + '/releases/tag/v0.1.5')
        self.assertTrue(latest.download_url.endswith('/EliteDangerousFilter.exe'))
        for tag in ('v0.1.4-r1', 'v0.1.4', 'v0.1.3'):
            self.assertIsNone(self.check(self.release(tag)))
        self.assertIsNotNone(self.check(self.release('v0.1.4-r2')))
        for field in ('draft', 'prerelease'):
            data = self.release()
            data[field] = True
            self.assertIsNone(self.check(data))
        with self.assertRaises(ValueError):
            self.check(self.release('v0.1.5-beta'))

    def test_missing_asset_and_untrusted_download_do_not_become_exe_links(self):
        data = self.release()
        data['html_url'] = 'https://evil.example/'
        for changes in (dict(browser_download_url='https://evil.example/payload.exe'),
                        dict(state='new'), dict(size=0), dict(size=True), dict(name='wrong.exe')):
            changed = copy.deepcopy(data)
            changed['assets'][0].update(changes)
            result = self.check(changed)
            self.assertIsNone(result.download_url)
            self.assertTrue(result.page_url.startswith(updates.PROJECT_URL + '/releases/tag/'))
        data['assets'] = []
        self.assertIsNone(self.check(data).download_url)

    def test_invalid_response_and_network_failure(self):
        for data in ([], {}, dict(self.release(), assets=None), dict(self.release(), draft='false')):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.check(data)
        for error in (URLError('offline'), TimeoutError(), HTTPError(updates.LATEST_API, 403, 'limited', {}, None)):
            with patch.object(updates, 'urlopen', side_effect=error), self.assertRaises(type(error)):
                updates.check_latest()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        for raw in (b'not json', b'x' * (updates.MAX_RESPONSE + 1)):
            response.read.return_value = raw
            with patch.object(updates, 'urlopen', return_value=response), self.assertRaises(ValueError):
                updates.check_latest()

    def controller(self):
        app = Mock(_closing=False)
        app.localizer.tr.side_effect = lambda text: text
        return updates.UpdateChecker(app, Mock(), Mock())

    def test_worker_dispatch_busy_and_close_guard(self):
        checker = self.controller()
        with patch.object(updates.threading, 'Thread') as thread, patch.object(updates, 'check_latest', return_value=None):
            checker.check()
            checker.check()
            thread.assert_called_once()
            self.assertTrue(thread.call_args.kwargs['daemon'])
            thread.call_args.kwargs['target']()
            checker.app._post.assert_called_once_with(checker.app.root, checker.finish, None, None, True)
        checker.app._closing = True
        with patch('localized_tk.messagebox.showinfo') as info:
            checker.finish(None, None, True)
            info.assert_not_called()

    def test_automatic_failures_and_no_update_are_silent_manual_is_not(self):
        checker = self.controller()
        with patch('localized_tk.messagebox.showwarning') as warn, patch('localized_tk.messagebox.showinfo') as info:
            checker.finish(None, URLError('offline'), False)
            checker.finish(None, None, False)
            warn.assert_not_called()
            info.assert_not_called()
            checker.finish(None, URLError('offline'), True)
            checker.finish(None, None, True)
            warn.assert_called_once()
            info.assert_called_once()

    def test_new_version_requires_confirmation_and_opens_release_page_only(self):
        checker = self.controller()
        release = updates.Release('v0.1.5', updates.PROJECT_URL + '/releases/tag/v0.1.5', None)
        with patch('localized_tk.messagebox.askyesno', return_value=False) as ask, patch.object(updates.webbrowser, 'open') as browser:
            checker.finish(release, None, False)
            ask.assert_called_once()
            browser.assert_not_called()
        with patch('localized_tk.messagebox.askyesno', return_value=True), patch.object(updates.webbrowser, 'open', return_value=False) as browser, patch('localized_tk.messagebox.showinfo') as info:
            checker.finish(release, None, True)
            browser.assert_called_once_with(release.page_url)
            self.assertIn(release.page_url, info.call_args.args[1])

    def test_packaged_verified_update_offers_download_without_opening_browser(self):
        checker = self.controller()
        release = updates.Release('v99.0.0', 'page', 'download', 'a' * 64, 100)
        with patch.object(updates.sys, 'frozen', True, create=True), patch.object(updates.sys, 'platform', 'win32'), \
                patch('localized_tk.messagebox.askyesno', return_value=True), \
                patch.object(checker, 'download') as download, patch.object(updates.webbrowser, 'open') as browser:
            checker.finish(release, None, True)
            download.assert_called_once_with(release)
            browser.assert_not_called()

    def test_install_cancel_prepare_error_and_save_refusal_never_commit(self):
        for case in ('cancel', 'download-failed', 'save-refused', 'save-exception', 'closed'):
            with self.subTest(case=case):
                checker = self.controller()
                prepared = Mock()
                checker.app._closing = case == 'closed'
                if case == 'save-exception':
                    checker.app.on_close.side_effect = OSError('save failed')
                with patch('localized_tk.messagebox.askyesno', return_value=case != 'cancel'), patch('localized_tk.messagebox.showwarning'):
                    checker.install(None if case == 'download-failed' else prepared,
                                    OSError('download failed') if case == 'download-failed' else None)
                prepared.commit.assert_not_called()
                if case != 'download-failed':
                    prepared.cancel.assert_called_once()

    def test_install_authorization_is_inside_normal_save_and_close_path(self):
        checker = self.controller()
        prepared = Mock()
        def close(before_destroy):
            prepared.commit.assert_not_called()
            before_destroy()
            checker.app._closing = True
        checker.app.on_close.side_effect = close
        with patch('localized_tk.messagebox.askyesno', return_value=True):
            checker.install(prepared, None)
        prepared.commit.assert_called_once()
        prepared.cancel.assert_not_called()
