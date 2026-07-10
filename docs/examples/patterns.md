# Patterns

These are useful, but they are not the first things most people need.

## Hide tiny inner loops

```python
--8<-- "snippets/patterns/hide_tiny_inner_loops.py"
```

<div id="cast-patterns-hide" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/patterns/hide_tiny_inner_loops.cast"></div>

This is a nice way to avoid visual noise when the inner work is too small to be
worth drawing every time.

## Keep a batch of bars on screen with `sustain()`

```python
--8<-- "snippets/patterns/sustain.py"
```

<div id="cast-patterns-sustain" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/patterns/sustain.cast"></div>

By default each bar owns the live display only for its own lifetime: when it
finishes it's committed to the terminal and the next bar opens a fresh display
below it, so you watch them one at a time. Wrap a batch in `sustain()` and a
single display spans the whole block — the bars stack and stay visible together
as a growing panel, with your `print()` and log output streaming above them.

Reach for it when the bars belong together and seeing them as a set matters (a
handful of related steps, or bars that finish out of order and you want held in
one place). For a long, purely sequential run, the default one-at-a-time
behavior is often what you want.

## Pause for interaction

```python
--8<-- "snippets/patterns/pause.py"
```

<div id="cast-patterns-pause" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/patterns/pause.cast"></div>

This is mostly a debugging or interactive convenience, but it is worth knowing
about.
