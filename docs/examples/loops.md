# Loops

The first thing to know is that `mqdm.mqdm(xs)` should feel as ordinary as
`tqdm.tqdm(xs)`.

## Simple sequential

```python
--8<-- "snippets/loops/simple.py"
```

<div id="cast-loops-simple" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/loops/simple.cast"></div>

That is the basic shape. In real code, this is usually all there is.

## Nested loops

```python
--8<-- "snippets/loops/nested.py"
```

<div id="cast-loops-nested" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/loops/nested.cast"></div>

This is one of the places `mqdm` starts to feel especially nice: nested bars
stay readable and visually calm.

## Dynamic descriptions

```python
--8<-- "snippets/loops/dynamic_desc.py"
```

<div id="cast-loops-dynamic" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/loops/dynamic_desc.cast"></div>

You can still set descriptions manually, but the callable `desc=` form is often
the cleanest way to keep the bar text close to the data being processed.

## Manual bars

Sometimes you are not iterating directly over the thing you want to count.

```python
--8<-- "snippets/loops/manual.py"
```

<div id="cast-loops-manual" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/loops/manual.cast"></div>

This is still very close to the manual `tqdm` style.
