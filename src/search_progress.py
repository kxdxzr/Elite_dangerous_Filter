"""Measured stage progress plus explicitly approximate, pause-aware whole-query ETA."""
import re
import time
import math
from collections import deque
from tkinter import TclError


def measure(message, detail=None):
    detail = detail or {}
    if 'done' in detail:
        return detail.get('done', 0), detail.get('work_total'), detail.get('stage', '')
    if 'scanned' in detail:
        total = detail.get('total', 0)
        # Spansh can cap its count at 10,000; do not call that a known total.
        return detail['scanned'], total if isinstance(total, (int, float)) and 0 < total < 10000 else None, '候选核查'
    match = re.search(r'RES 星系分页：(\d+)；已读取 (\d+) 个星系', message)
    if match:
        return int(match[2]), None, '候选星系'
    for pattern, stage in (
        (r'查询派系详情：(\d+)/(\d+)', '派系详情'),
        (r'Checking (\d+)/(\d+)', '候选核查'),
        (r'Body batches (\d+)/(\d+)', '天体批次'),
        (r'星环.*?(\d+)/(\d+)', '星环批次'),
        (r'任务来源控制派系：(\d+)/(\d+)', '来源控制派系'),
    ):
        match = re.search(pattern, message)
        if match:
            return int(match[1]), int(match[2]), stage
    return 0, None, ''


class OverallEstimate:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.elapsed = 0.0
        self.started = None
        self.work = {}
        self.samples = deque(maxlen=20)

    def begin(self, continuing=False):
        if not continuing:
            self.elapsed, self.work = 0.0, {}
        self.started = self.clock()
        # Replayed work and a long network pause must not bias the resumed rate.
        self.samples.clear()
        self.samples.append((self.seconds(), self.work.get('scanned', 0), self.work.get('hits', 0)))

    def seconds(self):
        return self.elapsed + (max(0, self.clock() - self.started) if self.started is not None else 0)

    def pause(self):
        self.elapsed = self.seconds()
        self.started = None

    def update(self, work):
        work = dict(work)
        for key in ('scanned', 'hits'):
            work[key] = max(work.get(key, 0), self.work.get(key, 0))
        self.work = work
        point = self.seconds(), work.get('scanned', 0), work.get('hits', 0)
        if not self.samples or point[1:] != self.samples[-1][1:]:
            self.samples.append(point)

    def remaining(self):
        if self.started is None or len(self.samples) < 3:
            return None
        first, last = self.samples[0], self.samples[-1]
        duration, done = last[0] - first[0], last[1] - first[1]
        if duration < 5 or done <= 0:
            return None
        if self.seconds() - last[0] > max(15, duration * 2):
            return None
        total, scanned = self.work.get('total'), self.work.get('scanned', 0)
        candidates = []
        if isinstance(total, (int, float)) and 0 < total < 10000:
            candidates.append(max(0, total - scanned))
        hits, wanted = self.work.get('hits', 0), self.work.get('want', 0)
        gained = last[2] - first[2]
        if gained >= 3 and wanted > 0:
            candidates.append(max(0, wanted - hits) * done / gained)
        if not candidates:
            return None
        # Page limit is an execution budget, not a claim of full catalogue size.
        if self.work.get('pages'):
            candidates.append(max(0, self.work['pages'] * self.work.get('per', 500) - scanned))
        estimate = min(candidates) * duration / done
        # Widen rather than claim precision when recent measured throughput varies.
        rates = [(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(self.samples, list(self.samples)[1:])
                 if b[0] - a[0] >= .1 and b[1] > a[1]]
        if len(rates) >= 3 and max(rates) > min(rates) * 10:
            return None
        return max(1, math.floor(estimate * .65)), max(2, math.ceil(estimate * 1.6))


def duration_text(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


class SearchProgress:
    def __init__(self, bar, label, localizer):
        self.bar, self.label, self.localizer = bar, label, localizer
        self.snapshot = ('', None)
        self.finished = 'idle'
        self.overall = None
        self.timer = None
        localizer.register(self.render)
        def dispose(event):
            if event.widget is bar:
                if self.timer is not None:
                    try:
                        bar.after_cancel(self.timer)
                    except TclError:
                        pass
                localizer.callbacks.discard(self.render)
                try:
                    bar.stop()
                except TclError:
                    pass  # Tk may already have removed the widget command.
        bar.bind('<Destroy>', dispose, add='+')

    def begin(self, continuing=False):
        if self.overall is None:
            self.overall = OverallEstimate()
        self.overall.begin(continuing)
        self.finished = None
        if self.timer is not None:
            self.bar.after_cancel(self.timer)
        self.timer = self.bar.after(1000, self.tick)

    def tick(self):
        self.timer = None
        if self.finished is None and self.bar.winfo_exists():
            self.render()
            self.timer = self.bar.after(1000, self.tick)

    def update(self, message='', detail=None):
        self.snapshot, self.finished = (message, detail), None
        if self.overall is not None and (detail or {}).get('overall'):
            self.overall.update(detail['overall'])
        self.render()

    def with_overall(self, text):
        if self.overall is None:
            return text
        work = self.overall.work
        total = work.get('total')
        coverage = f"{work.get('scanned', 0):,}/" + (f'{total:,}' if isinstance(total, (int, float)) and 0 < total < 10000 else '?')
        remaining = self.overall.remaining()
        eta = (duration_text(remaining[0]) + '–' + duration_text(remaining[1])
               if remaining else self.localizer.tr('估算中／暂无法可靠估算' if self.finished is None else '已暂停／结束'))
        summary = self.localizer.message('progress.overall', page=work.get('page', 1),
            coverage=coverage, hits=work.get('hits', 0), want=work.get('want', '?'),
            step=work.get('step', 1), steps=work.get('steps', '?'),
            elapsed=duration_text(self.overall.seconds()), eta=eta)
        return summary + '\n' + text

    def render(self):
        if not self.bar.winfo_exists():
            self.localizer.callbacks.discard(self.render)
            return
        if self.finished == 'idle':
            self.bar.configure(mode='determinate', value=0)
            self.label.set(self.localizer.tr('等待查询'))
            return
        if self.finished is not None:
            self.bar.stop()
            self.bar.configure(mode='determinate')
            if self.finished:
                self.bar.configure(value=100)
            self.label.set(self.with_overall(self.localizer.tr('检索完成' if self.finished else '已结束／未完成，详见状态')))
            return
        message, detail = self.snapshot
        done, total, stage = measure(message, detail)
        stage = self.localizer.tr(stage or '当前阶段')
        if isinstance(total, (int, float)) and total > 0:
            self.bar.stop()
            self.bar.configure(mode='determinate', maximum=100, value=min(100, 100 * done / total))
            self.label.set(self.with_overall(f'{stage}: {done:,}/{total:,} ({min(100, 100 * done / total):.1f}%)'))
        else:
            self.bar.stop()
            # Unknown work is a count/status, not a fabricated percentage or
            # a bouncing animation which hides already measured stage progress.
            self.bar.configure(mode='determinate', maximum=100, value=0)
            self.label.set(self.with_overall(self.localizer.message('progress.unknown', stage=stage, done=done)))

    def finish(self, complete=False):
        if self.overall is not None:
            self.overall.pause()
        if self.timer is not None:
            self.bar.after_cancel(self.timer)
            self.timer = None
        self.finished = bool(complete)
        self.render()
