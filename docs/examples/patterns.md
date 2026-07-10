# Patterns

These are useful, but they are not the first things most people need.

## To `leave` or not to `leave`

You can decide whether progress bars should stay on the screen after completion or disappear using the `leave` parameter.

```python
--8<-- "snippets/patterns/leave.py"
```

<div id="cast-patterns-leave" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/patterns/leave.cast"></div>

## Hide tiny inner loops

You can conditionally disable progress bars.

```python
--8<-- "snippets/patterns/hide_tiny_inner_loops.py"
```

<div id="cast-patterns-hide" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/patterns/hide_tiny_inner_loops.cast"></div>

This is a nice way to avoid visual noise when the inner work is too small to be
worth drawing every time.

## `advance` (fast) vs `update`

There are 3 primary ways to manually update a progress bar: `update(n, **options)`, `advance(n)`, and `set(**options)`.

- `set()` is the most general way to update progress bar fields.
- `update(n, **kw)` is essentially `set(advance=n,  **kw)` - the only difference from `set()` is that by default, it will increment the progress bar by 1.
- `advance(n)` is a performance-tuned way to advance the progress bar without the overhead of a full update. It runs 10–20× faster in tight loops and uses batched advances tied to the configured refresh rate, for efficiency. This is especially helpful for cross-process scenarios.

```python
--8<-- "snippets/patterns/fast_advance.py"
```

<div id="cast-patterns-fast-advance" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/patterns/fast_advance.cast"></div>

Iterating with `for x in mqdm(...)` already uses `advance` internally.

## Update options with `set()`

```python
--8<-- "snippets/patterns/set.py"
```

<div id="cast-patterns-set" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/patterns/set.cast"></div>

`set()` changes any field of a live bar:

- `completed=` sets the counter to an absolute value; `advance=` moves it relatively.
- `total=` rescales the bar mid-run.
- `description=` relabels it; a callable `desc=lambda item, i: ...` is reused each
  step (and on `advance`'s fast path via `arg=`).
- `visible=` hides or shows it; `leave=`/`transient=` control whether the row
  stays after it finishes.
- any other keyword becomes a custom task field, for use with custom columns.

Pass several at once to change them together, or reuse one bar across phases —
step 3 turns the download bar into the verification bar.

## Keep bars alive with `sustain()`

By default, closing a bar will freeze its display and prevent further updates. 

You can use `sustain()` to keep the bars from detaching so that your prints will go above 
the group of progress bars instead of in between them.

```python
--8<-- "snippets/patterns/sustain.py"
```

<div id="cast-patterns-sustain" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/patterns/sustain.cast"></div>

## Pause for interaction

Use pause when you want to do something like open an interactive shell in the middle of a loop. e.g.

```python
--8<-- "snippets/patterns/pause.py"
```

<div id="cast-patterns-pause" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/patterns/pause.cast"></div>

## Reading files

Show file reading with byte-oriented progress.

```python
--8<-- "snippets/output/open_bytes.py"
```

<div id="cast-output-open_bytes" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/output/open_bytes.cast"></div>
