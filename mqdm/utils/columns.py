import time
from rich import progress
from rich.segment import Segment
from rich.style import Style
from rich.progress_bar import ProgressBar
from rich.spinner import SPINNERS


class TwoToneBar(ProgressBar):
    """A progress bar with a lighter fill for work that's started but not done.

    Renders three zones — completed, started-but-pending, and idle — so you can
    see how far the workers have run ahead of what has actually finished. Reads
    the pending count from ``started`` (defaults to ``completed``, i.e. a plain
    bar) and clamps it to ``completed <= started <= total``.

    The started zone defaults to a dimmed shade of the complete colour (same hue,
    lower intensity). That reads as "same work, in progress" and — because dim is
    an SGR attribute rather than a colour — stays distinct from the grey
    background even on 16-colour terminals, where a lighter grey would collapse
    into it. Pass ``started_style`` to override.
    """
    def __init__(self, *args, started: float = 0, started_style: str | None = None, **kw):
        super().__init__(*args, **kw)
        self.started = started
        self.started_style = started_style

    def _resolve_started_style(self, console) -> Style:
        if self.started_style is not None:
            return console.get_style(self.started_style)
        return console.get_style(self.complete_style) + Style(dim=True)

    def __rich_console__(self, console, options):
        width = min(self.width or options.max_width, options.max_width)
        # Defer to the stock bar for indeterminate / pulsing tasks.
        if self.total is None or self.pulse:
            yield from super().__rich_console__(console, options)
            return

        bar = "-" if (options.legacy_windows or options.ascii_only) else "━"
        done = max(0.0, min(self.total, self.completed))
        started = max(done, min(self.total, self.started))
        done_cells = int(round(width * done / self.total)) if self.total else 0
        started_cells = int(round(width * started / self.total)) if self.total else 0

        finished = self.total and self.completed >= self.total
        zones = (
            (done_cells, console.get_style(self.finished_style if finished else self.complete_style)),
            (started_cells - done_cells, self._resolve_started_style(console)),
            (width - started_cells, console.get_style(self.style)),
        )
        for count, style in zones:
            if count > 0:
                yield Segment(bar * count, style)


class TwoToneColumn(progress.BarColumn):
    """``BarColumn`` that shades a task's ``started`` field as a second tone."""
    def __init__(self, *args, started_style: str | None = None, **kw):
        self.started_style = started_style
        super().__init__(*args, **kw)

    def render(self, task) -> ProgressBar:
        return TwoToneBar(
            total=max(0, task.total) if task.total is not None else None,
            completed=max(0, task.completed),
            started=max(0, task.fields.get("started", task.completed)),
            width=None if self.bar_width is None else max(1, self.bar_width),
            pulse=not task.started,
            animation_time=task.get_time(),
            style=self.style,
            complete_style=self.complete_style,
            finished_style=self.finished_style,
            pulse_style=self.pulse_style,
            started_style=self.started_style,
        )


class MofNColumn(progress.DownloadColumn):
    '''A progress column that shows the current vs. total count of items.'''
    def __init__(self, bytes=False, separator="/", **kw):
        self.bytes = bytes
        self.separator = separator
        super().__init__(**kw)

    def render(self, task):
        bytes = task.fields.get("bytes", self.bytes)
        if bytes:
            return super().render(task)
        total = f'{int(task.total):,}' if task.total is not None else "?"
        return progress.Text(
            f"{int(task.completed):,d}{self.separator}{total}",
            style="progress.download",
            justify='right'
        )


class SpeedColumn(progress.TransferSpeedColumn):
    """Renders human readable transfer speed."""
    def __init__(self, bytes=False, unit_scale=1, **kw):
        self.bytes = bytes
        self.unit_scale = unit_scale
        super().__init__(**kw)

    def render(self, task):
        """Show data transfer speed."""
        bytes = task.fields.get("bytes", self.bytes)
        if bytes:
            return super().render(task)
        speed = task.finished_speed or task.speed
        if speed is None:
            return progress.Text("", style="progress.data.speed")
        end = '/s'
        if 0 < speed < 1:
            speed = 1 / speed
            speed, suffix = time_units(speed)
            end = '/x'
            return progress.Text(f"{speed:.1f}{suffix}{end}", justify='right', style="progress.data.speed")
        unit, suffix = progress.filesize.pick_unit_and_suffix(
            int(speed), 
            ["x", "K", "M", "B", "T"], 
            # ["", "×10³", "×10⁶", "×10⁹", "×10¹²"], 
            1000)
        return progress.Text(f"{speed/unit:.1f}{suffix}{end}", justify='right', style="progress.data.speed")

def time_units(seconds):
    for d, u in [(60, 's'), (60, 'm'), (24, 'h'), (365, 'd')]:
        if seconds < d:
            return seconds, u
        seconds /= d
    return seconds, 'y'


class TimeElapsedColumn(progress.TimeRemainingColumn):
    """Renders time elapsed."""
    def __init__(self, compact: bool = False, **kw):
        self._compact = compact
        super().__init__(**kw)

    def render(self, task):
        """Show time elapsed."""
        elapsed = task.finished_time if task.finished else task.elapsed
        if elapsed is None:
            return progress.Text("--:--" if self._compact else "-:--:--", style="progress.elapsed")
        minutes, seconds = divmod(int(elapsed), 60)
        hours, minutes = divmod(minutes, 60)
        return progress.Text(
            (f"{hours:d}:" if hours or not self._compact else "") + 
            f"{minutes:02d}:{seconds:02d}", style="progress.elapsed")



# class LogBarColumn(progress.BarColumn):
#     def render(self, task):
#         return progress.Group(
#             super().render(task),
#             progress.Text(task.description, style="progress.description"),
#         )

