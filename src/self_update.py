"""Verified Windows update staging; a separate helper replaces the stopped EXE."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen

from app_metadata import PROJECT_NAME, PROJECT_VERSION
from file_io import atomic_write


MAX_EXE = 256 * 1024 * 1024
HELPER = r'''param([string]$Config)
$ErrorActionPreference = 'Stop'
$c = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$changed = $false
$phase = 'Waiting for update authorization'
try {
    $parent = $null
    try { $parent = [Diagnostics.Process]::GetProcessById([int]$c.pid) } catch {}
    [IO.File]::WriteAllText($c.ready, 'ready')
    $deadline = [DateTime]::UtcNow.AddMinutes(5)
    while (!(Test-Path -LiteralPath $c.go)) {
        if ([DateTime]::UtcNow -gt $deadline) { exit 0 }
        Start-Sleep -Milliseconds 100
    }
    $phase = 'Waiting for old process to exit'
    if ($parent -and !$parent.WaitForExit(60000)) { throw 'Old process did not exit; update cancelled.' }
    $phase = 'Verifying staged EXE hash'
    if ((Get-FileHash -LiteralPath $c.staged -Algorithm SHA256).Hash.ToLowerInvariant() -ne $c.sha256) {
        throw 'Staged EXE hash changed; update cancelled.'
    }
    $phase = 'Replacing EXE and backing up old file'
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while ($true) {
        try {
            [IO.File]::Replace($c.staged, $c.target, $c.backup, $true)
            $changed = $true
            break
        } catch {
            if ([DateTime]::UtcNow -gt $deadline) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
    $phase = 'Launching updated EXE'
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $c.target
    $start.WorkingDirectory = [IO.Path]::GetDirectoryName($c.target)
    $start.UseShellExecute = $false
    $start.EnvironmentVariables['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    $process = [Diagnostics.Process]::Start($start)
    if (!$process) { throw 'Unable to launch updated EXE.' }
    [IO.File]::WriteAllText($c.log, 'Update installed; old EXE retained at ' + $c.backup)
} catch {
    $failure = $phase + "`n" + $_.Exception.ToString()
    if ($changed) {
        try {
            [IO.File]::Replace($c.backup, $c.target, $c.failed, $true)
            $restart = New-Object Diagnostics.ProcessStartInfo
            $restart.FileName = $c.target
            $restart.WorkingDirectory = [IO.Path]::GetDirectoryName($c.target)
            $restart.UseShellExecute = $false
            $restart.EnvironmentVariables['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
            [void][Diagnostics.Process]::Start($restart)
            $failure += "`nOld EXE restored."
        } catch { $failure += "`nRestore failed: " + $_.Exception.Message }
    }
    [IO.File]::WriteAllText($c.log, $failure)
    if ($c.notify) {
        Add-Type -AssemblyName PresentationFramework
        [void][Windows.MessageBox]::Show($failure + "`nLog: " + $c.log, 'Elite Dangerous Filter update failed')
    }
    exit 1
}
'''


@dataclass
class PreparedUpdate:
    folder: Path
    process: object

    def commit(self):
        if self.process.poll() is not None:
            raise OSError('Update helper exited before replacement was authorized')
        atomic_write(self.folder / 'go', b'update')

    def cancel(self):
        if self.process.poll() is None:
            self.process.terminate()


def prepare_update(release, target):
    """Download before shutdown; fail closed without an API SHA256 digest."""
    from release_updates import PROJECT_URL, version_key
    from urllib.parse import quote
    expected_url = f'{PROJECT_URL}/releases/download/{quote(release.version, safe="")}/EliteDangerousFilter.exe'
    if (release.download_url != expected_url or not release.sha256
            or version_key(release.version) <= version_key(PROJECT_VERSION)
            or not 0 < release.size <= MAX_EXE):
        raise ValueError('Update metadata is missing, invalid or not newer')
    import re
    if not re.fullmatch('[0-9a-f]{64}', release.sha256):
        raise ValueError('Invalid update SHA256')
    target = Path(target).resolve(strict=True)
    if target.suffix.lower() != '.exe':
        raise ValueError('Only a packaged EXE can be updated')
    # Beside the target: same-volume replacement, and a real directory-write test.
    folder = Path(tempfile.mkdtemp(prefix='.edf-update-', dir=target.parent))
    staged = folder / 'new.exe'
    request = Request(expected_url, headers={'User-Agent': f'{PROJECT_NAME}/{PROJECT_VERSION}'})
    digest, received = hashlib.sha256(), 0
    try:
        with urlopen(request, timeout=30) as response, staged.open('xb') as stream:
            deadline = time.monotonic() + 600
            while True:
                chunk = response.read(128 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > release.size or time.monotonic() > deadline:
                    raise ValueError('Update download exceeds expected size or time limit')
                digest.update(chunk)
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if received != release.size or digest.hexdigest() != release.sha256:
            raise ValueError('Update size or SHA256 mismatch')
        with staged.open('rb') as stream:
            if stream.read(2) != b'MZ':
                raise ValueError('Update is not a Windows executable')
        script, config = folder / 'replace.ps1', folder / 'update.json'
        atomic_write(script, HELPER.encode('utf-8-sig'))
        values = dict(pid=os.getpid(), notify=True, target=str(target), staged=str(staged), sha256=release.sha256,
                      backup=str(folder / 'previous.exe'), failed=str(folder / 'failed.exe'),
                      ready=str(folder / 'ready'), go=str(folder / 'go'), log=str(folder / 'update.log'))
        atomic_write(config, json.dumps(values).encode('utf-8'))
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        process = subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                    '-File', str(script), '-Config', str(config)],
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        prepared = PreparedUpdate(folder, process)
        deadline = time.monotonic() + 10
        while not (folder / 'ready').exists():
            if process.poll() is not None or time.monotonic() > deadline:
                prepared.cancel()
                raise OSError('Update helper could not start')
            time.sleep(.05)
        return prepared
    except Exception:
        staged.unlink(missing_ok=True)
        raise
