# Output

`mqdm` is most useful once your work does more than quietly iterate.

These patterns keep terminal output readable while progress bars are active.

## Printing above the bars

Use `mqdm.print(...)` instead of the builtin `print(...)` when you want output
to land above the live progress region.

```python
--8<-- "snippets/output/print.py"
```

<div id="cast-output-print" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/output/print.cast"></div>

## Logging

Use `mqdm.install_logging()` to attach a handler that routes logging records
through the runtime, so they render above the bars instead of tearing through
them.

```python
--8<-- "snippets/output/log.py"
```

<div id="cast-output-log" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/output/log.cast"></div>

This is especially useful once workers, nested bars, or warnings are involved.

## Byte-oriented progress

For file or stream work, create a bar with `bytes=True` and advance it by the
number of bytes processed.

```python
--8<-- "snippets/output/open_bytes.py"
```

<div id="cast-output-open-bytes" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/output/open_bytes.cast"></div>

## Customizing columns

The columns a bar renders are a runtime option — pass a `columns` tuple in
`backend_options`. Use `mqdm.configure(columns=...)` to set it for the default
runtime, or a separate `mqdm.Runtime(backend_options={"columns": ...})` to run
different layouts side by side. Entries are Rich `ProgressColumn`s (or format
strings); mqdm's own columns are in `mqdm.columns`, and you can write your own
to render per-task fields.

```python
--8<-- "snippets/output/columns.py"
```

<div id="cast-output-columns" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/output/columns.cast"></div>

