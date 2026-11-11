"""Bounded, opt-in local Journal position snapshots; no game/network dependency."""
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re

MAX_SCAN_BYTES = 16 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
MAX_LINE_BYTES = 1024 * 1024
MAX_FILES = 5000
JOURNAL_NAME = re.compile(r'Journal\.(.+)\.(\d+)\.log', re.I)
LOCATION_EVENTS = {'Location', 'FSDJump', 'CarrierJump'}


@dataclass(frozen=True)
class JournalLocation:
    system: str
    timestamp: str
    filename: str


def default_directory():
    return str(Path.home() / 'Saved Games' / 'Frontier Developments' / 'Elite Dangerous')


def reverse_lines(file, budget):
    """Yield complete lines newest first; never interpret a still-written tail."""
    file.seek(0, 2)
    position, pending, tail = file.tell(), b'', True
    while position and budget[0] > 0:
        size = min(position, CHUNK_BYTES, budget[0])
        position -= size
        budget[0] -= size
        file.seek(position)
        parts = (file.read(size) + pending).split(b'\n')
        pending = parts[0]
        if len(pending) > MAX_LINE_BYTES:
            raise ValueError('日志行过长，无法安全读取当前位置。')
        if tail:
            if len(parts) == 1:
                continue
            # Whether empty or incomplete, the final segment is not a line.
            parts.pop()
            tail = False
        for line in reversed(parts[1:]):
            if len(line) > MAX_LINE_BYTES:
                raise ValueError('日志行过长，无法安全读取当前位置。')
            if line.strip():
                yield line
    if position == 0 and pending.strip() and not tail:
        yield pending.removeprefix(b'\xef\xbb\xbf')


def parse_location(line, filename):
    try:
        record = json.loads(line.decode('utf-8-sig'))
    except (ValueError, RecursionError):
        return None
    if not isinstance(record, dict) or record.get('event') not in LOCATION_EVENTS:
        return None
    system, stamp = record.get('StarSystem'), record.get('timestamp')
    invalid = '日志中的位置信息无效，请等待游戏写入新的位置记录。'
    if (not isinstance(system, str) or not system.strip() or len(system) > 256
            or any(ord(c) < 32 or 127 <= ord(c) < 160 for c in system)
            or not isinstance(stamp, str)):
        raise ValueError(invalid)
    try:
        parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError
    except ValueError:
        raise ValueError(invalid) from None
    return JournalLocation(system.strip(), stamp, filename)


def read_current_system(directory):
    folder = Path(directory)
    if not folder.is_dir():
        raise ValueError('未找到游戏日志文件夹，请选择 Journal 所在文件夹。')
    files = []
    for path in folder.iterdir():
        match = JOURNAL_NAME.fullmatch(path.name)
        if match and path.is_file():
            files.append((path.stat().st_mtime_ns, path, match.group(1), int(match.group(2))))
            if len(files) > MAX_FILES:
                raise ValueError('日志文件过多，请选择只含近期 Journal 的文件夹。')
    if not files:
        raise ValueError('文件夹中没有 Journal 日志，请先进入游戏或选择其他文件夹。')
    latest = max(files, key=lambda item: (item[0], item[1].name))
    parts = sorted((item for item in files if item[2] == latest[2]), key=lambda item: item[3], reverse=True)
    budget = [MAX_SCAN_BYTES]
    for _, path, _, _ in parts:
        with path.open('rb') as file:
            for line in reverse_lines(file, budget):
                location = parse_location(line, path.name)
                if location is not None:
                    return location
        if budget[0] <= 0:
            raise ValueError('近期日志过大且未找到位置，请在游戏中更新位置后重试。')
    raise ValueError('最新游戏会话尚无位置记录，请进入游戏后重试。')
