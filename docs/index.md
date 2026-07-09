# mqdm

<div class="hero">
  <div class="hero-copy">
    <p class="eyebrow">tqdm for parallel work</p>
    <h1>progress bars for threads, processes, and nested work</h1>
    <p class="lede">
      <code>mqdm</code> keeps the familiar <code>tqdm</code>-style loop shape,
      but is built for code that also needs worker pools, nested progress, and
      terminal output that does not fight the bars.
    </p>
  </div>
  <div class="hero-art">
    <img src="assets/image.png" alt="mqdm progress bar illustration" />
  </div>
</div>

<div id="cast-home-main" class="asciinema-player mqdm-cast" data-cast-src="assets/casts/home/main.cast" data-cols="80"></div>

## The basic shape

```python
--8<-- "snippets/home/basic_shape.py"
```

<div id="cast-home-basic" class="asciinema-player mqdm-cast" data-cast-src="assets/casts/home/basic_shape.cast"></div>

## Why mqdm?

`mqdm` gives you:

- `tqdm`-style progress bars
- worker-pool execution with `concurrent.futures` (process and thread)
- automatic nested progress bars across parallel workers
- progress-safe printing and logging
- pretty progress bars, powered by `rich`

The same shape also seamlessly scales to parallel work:

```python
--8<-- "snippets/home/why_mqdm.py"
```

<div id="cast-home-why" class="asciinema-player mqdm-cast" data-cast-src="assets/casts/home/why_mqdm.cast"></div>

## Some examples

1. [Loops](examples/loops.md)
2. [Pools](examples/pools.md)
3. [Output](examples/output.md)
4. [Patterns](examples/patterns.md)

For the full API, see [API reference](api/index.md). For an end-to-end example, start with [Examples](examples/index.md).
