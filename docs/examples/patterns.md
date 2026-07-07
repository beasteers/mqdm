# Patterns

These are useful, but they are not the first things most people need.

## Hide tiny inner loops

```python
--8<-- "snippets/patterns/hide_tiny_inner_loops.py"
```

<div id="cast-patterns-hide" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/patterns/hide_tiny_inner_loops.cast"></div>

This is a nice way to avoid visual noise when the inner work is too small to be
worth drawing every time.

## Keep completed bars visible inside a group

```python
--8<-- "snippets/patterns/group.py"
```

<div id="cast-patterns-group" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/patterns/group.cast"></div>

`group()` is handy when you want a small family of bars to stay visible until
the whole grouped operation finishes.

## Pause for interaction

```python
--8<-- "snippets/patterns/pause.py"
```

<div id="cast-patterns-pause" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/patterns/pause.cast"></div>

This is mostly a debugging or interactive convenience, but it is worth knowing
about.
