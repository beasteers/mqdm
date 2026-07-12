# Columns

Progress columns for customizing bar layout. Pass a `columns` tuple via a
runtime's `backend_options` (see the [Customizing columns](../examples/output.md#customizing-columns)
example) — entries are Rich `ProgressColumn`s or format strings, and these are
mqdm's own. Write your own by subclassing `rich.progress.ProgressColumn`.

::: mqdm.columns.TwoToneColumn
    options:
      show_root_heading: true
      show_source: false

::: mqdm.columns.MofNColumn
    options:
      show_root_heading: true
      show_source: false

::: mqdm.columns.SpeedColumn
    options:
      show_root_heading: true
      show_source: false

::: mqdm.columns.TimeElapsedColumn
    options:
      show_root_heading: true
      show_source: false


The following column objects are available from `rich.progress`:

 * [`BarColumn`](https://rich.readthedocs.io/en/stable/reference/progress.html#rich.progress.BarColumn) Displays the bar.
 * [`TextColumn`](https://rich.readthedocs.io/en/stable/reference/progress.html#rich.progress.TextColumn) Displays text.
 * [`TimeElapsedColumn`](https://rich.readthedocs.io/en/stable/reference/progress.html#rich.progress.TimeElapsedColumn) Displays the time elapsed.
 * [`TimeRemainingColumn`](https://rich.readthedocs.io/en/stable/reference/progress.html#rich.progress.TimeRemainingColumn) Displays the estimated time remaining.
 * [`MofNCompleteColumn`](https://rich.readthedocs.io/en/stable/reference/progress.html#rich.progress.MofNCompleteColumn) Displays completion progress as "{task.completed}/{task.total}" (works best if completed and total are ints).
 * [`FileSizeColumn`](https://rich.readthedocs.io/en/stable/reference/progress.html#rich.progress.FileSizeColumn) Displays progress as file size (assumes the steps are bytes).
 * [`TotalFileSizeColumn`](https://rich.readthedocs.io/en/stable/reference/progress.html#rich.progress.TotalFileSizeColumn) Displays total file size (assumes the steps are bytes).
 * [`DownloadColumn`](https://rich.readthedocs.io/en/stable/reference/progress.html#rich.progress.DownloadColumn) Displays download progress (assumes the steps are bytes).
 * [`TransferSpeedColumn`](https://rich.readthedocs.io/en/stable/reference/progress.html#rich.progress.TransferSpeedColumn) Displays transfer speed (assumes the steps are bytes).
 * [`SpinnerColumn`](https://rich.readthedocs.io/en/stable/reference/progress.html#rich.progress.SpinnerColumn) Displays a "spinner" animation.
 * [`RenderableColumn`](https://rich.readthedocs.io/en/stable/reference/progress.html#rich.progress.RenderableColumn) Displays an arbitrary Rich renderable in the column.

