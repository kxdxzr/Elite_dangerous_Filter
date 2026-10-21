"""Honest stage progress: known work counts, never a guessed end-to-end ETA."""
import re
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


class SearchProgress:
    def __init__(self, bar, label, localizer):
        self.bar, self.label, self.localizer = bar, label, localizer
        self.snapshot = ('', None)
        self.finished = 'idle'
        localizer.register(self.render)
        def dispose(event):
            if event.widget is bar:
                localizer.callbacks.discard(self.render)
                try:
                    bar.stop()
                except TclError:
                    pass  # Tk may already have removed the widget command.
        bar.bind('<Destroy>', dispose, add='+')

    def update(self, message='', detail=None):
        self.snapshot, self.finished = (message, detail), None
        self.render()

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
            self.label.set(self.localizer.tr('检索完成' if self.finished else '已结束／未完成，详见状态'))
            return
        message, detail = self.snapshot
        done, total, stage = measure(message, detail)
        stage = self.localizer.tr(stage or '当前阶段')
        if isinstance(total, (int, float)) and total > 0:
            self.bar.stop()
            self.bar.configure(mode='determinate', maximum=100, value=min(100, 100 * done / total))
            self.label.set(f'{stage}: {done:,}/{total:,} ({min(100, 100 * done / total):.1f}%)')
        else:
            self.bar.stop()
            # Unknown work is a count/status, not a fabricated percentage or
            # a bouncing animation which hides already measured stage progress.
            self.bar.configure(mode='determinate', maximum=100, value=0)
            self.label.set(self.localizer.message('progress.unknown', stage=stage, done=done))

    def finish(self, complete=False):
        self.finished = bool(complete)
        self.render()
