"""GitHub release detection and confirmed, verified Windows self-update UI."""
from dataclasses import dataclass
import json
import re
import threading
import sys
from urllib.parse import quote
from urllib.request import Request, urlopen
import webbrowser

from app_metadata import PROJECT_AUTHOR, PROJECT_NAME, PROJECT_URL, PROJECT_VERSION


LATEST_API = f'https://api.github.com/repos/{PROJECT_AUTHOR}/{PROJECT_NAME}/releases/latest'
MAX_RESPONSE = 2 * 1024 * 1024


def should_auto_check(frozen, argv):
    return bool(frozen) and not any(flag in argv for flag in ('--smoke-test', '--session-test'))


def version_key(value):
    """Project revisions (-rN) are stable upgrades, not SemVer prereleases."""
    if not isinstance(value, str):
        raise ValueError('Invalid release version')
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?', value)
    if not match:
        raise ValueError('Invalid release version')
    suffix = match[4]
    revision = re.fullmatch(r'r(\d+)', suffix or '')
    return (*map(int, match.group(1, 2, 3)),
            1 if suffix is None or revision else 0, int(revision[1]) if revision else 0)


@dataclass(frozen=True)
class Release:
    version: str
    page_url: str
    download_url: str | None
    sha256: str | None = None
    size: int = 0


def check_latest(current=PROJECT_VERSION):
    """One bounded HTTPS request, no token, cache, settings or filesystem writes."""
    current_key = version_key(current)
    request = Request(LATEST_API, headers={
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2026-03-10',
        'User-Agent': f'{PROJECT_NAME}/{PROJECT_VERSION}',
    })
    with urlopen(request, timeout=12) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError('Release response too large')
    data = json.loads(raw)
    if not isinstance(data, dict) or type(data.get('draft')) is not bool or type(data.get('prerelease')) is not bool:
        raise ValueError('Invalid release response')
    if data['draft'] or data['prerelease']:
        return None
    tag = data.get('tag_name')
    latest_key = version_key(tag)
    if latest_key[3] != 1:
        raise ValueError('Expected a stable release tag')
    if latest_key <= current_key:
        return None
    # Construct URLs from our pinned repository; never open arbitrary response URLs.
    page = f'{PROJECT_URL}/releases/tag/{quote(tag, safe="")}'
    download = f'{PROJECT_URL}/releases/download/{quote(tag, safe="")}/EliteDangerousFilter.exe'
    assets = data.get('assets')
    if not isinstance(assets, list):
        raise ValueError('Invalid release assets')
    ready = any(isinstance(asset, dict) and asset.get('name') == 'EliteDangerousFilter.exe'
                and asset.get('state') == 'uploaded' and type(asset.get('size')) is int
                and asset['size'] > 0 and asset.get('browser_download_url') == download for asset in assets)
    asset = next((a for a in assets if isinstance(a, dict) and a.get('name') == 'EliteDangerousFilter.exe'
                  and a.get('browser_download_url') == download and a.get('state') == 'uploaded'
                  and type(a.get('size')) is int and a['size'] > 0), {})
    digest = asset.get('digest', '')
    sha256 = digest[7:].lower() if isinstance(digest, str) and re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest) else None
    return Release(tag, page, download if ready else None, sha256, asset.get('size', 0))


class UpdateChecker:
    """Dispatch worker completion through the application's existing Tk queue."""
    def __init__(self, app, button, status):
        self.app, self.button, self.status = app, button, status
        self.busy = False

    def check(self, manual=True):
        if self.busy or self.app._closing:
            return
        self.busy = True
        self.button.configure(state='disabled')
        self.status.set(self.app.localizer.tr('正在检查更新…'))

        def worker():
            try:
                release, error = check_latest(), None
            except Exception as exc:
                release, error = None, exc
            self.app._post(self.app.root, self.finish, release, error, manual)
        threading.Thread(target=worker, daemon=True).start()

    def finish(self, release, error, manual):
        self.busy = False
        if self.app._closing:
            return
        from localized_tk import messagebox
        tr = self.app.localizer.tr
        self.button.configure(state='normal')
        self.status.set('')
        if error is not None:
            if manual:
                messagebox.showwarning(tr('检查更新'), tr('暂时无法检查更新，请检查网络或稍后重试。'), parent=self.app.root)
            return
        if release is None:
            if manual:
                messagebox.showinfo(tr('检查更新'), tr('当前已是最新版本，或本地版本更新。'), parent=self.app.root)
            return
        if getattr(sys, 'frozen', False) and sys.platform == 'win32' and release.download_url and release.sha256:
            if messagebox.askyesno(tr('发现新版本'), tr('发现新版 {latest}，下载并校验更新？当前程序会继续运行，完成后再确认退出替换。').format(latest=release.version), parent=self.app.root):
                self.download(release)
            return
        prompt = tr('当前版本：{current}\n最新版本：{latest}\n\n打开 GitHub 发布页下载更新？\n下载后请退出旧程序，再手动替换 EXE；保留本地数据。').format(
            current=PROJECT_VERSION, latest=release.version)
        if release.download_url is None:
            prompt += '\n\n' + tr('该版本暂未提供 Windows EXE，请查看发布说明。')
        if messagebox.askyesno(tr('发现新版本'), prompt, parent=self.app.root):
            try:
                opened = webbrowser.open(release.page_url)
            except Exception:
                opened = False
            if not opened:
                messagebox.showinfo(tr('检查更新'), tr('请在浏览器中打开：') + '\n' + release.page_url, parent=self.app.root)

    def download(self, release):
        self.busy = True
        self.button.configure(state='disabled')
        self.status.set(self.app.localizer.tr('正在下载并校验更新…'))
        def worker():
            from self_update import prepare_update
            try:
                prepared, error = prepare_update(release, sys.executable), None
            except Exception as exc:
                prepared, error = None, exc
            self.app._post(self.app.root, self.install, prepared, error)
        threading.Thread(target=worker, daemon=True).start()

    def install(self, prepared, error):
        from localized_tk import messagebox
        self.busy = False
        if self.app._closing:
            if prepared:
                prepared.cancel()
            return
        tr = self.app.localizer.tr
        self.button.configure(state='normal')
        self.status.set('')
        if error is not None:
            messagebox.showwarning(tr('检查更新'), tr('更新准备失败，当前程序未改动。请检查网络、磁盘空间和目录权限，或手动下载更新。'), parent=self.app.root)
            return
        if not messagebox.askyesno(tr('发现新版本'), tr('更新已校验。现在保存条件并退出、替换和重启？正在进行的查询将中断，结果和断点不保证恢复。旧 EXE 将保留备份。'), parent=self.app.root):
            prepared.cancel()
            return
        try:
            # on_close refuses to exit if session saving fails; never authorize then.
            self.app.on_close(before_destroy=prepared.commit)
            if not self.app._closing:
                prepared.cancel()
        except Exception:
            prepared.cancel()
            messagebox.showwarning(tr('检查更新'), tr('更新准备失败，当前程序未改动。请检查网络、磁盘空间和目录权限，或手动下载更新。'), parent=self.app.root)
