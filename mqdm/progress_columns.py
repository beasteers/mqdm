import time
from rich import progress



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
            return progress.Text(f"{speed}", style="progress.data.speed")
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

