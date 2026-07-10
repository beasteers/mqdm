# Loops

Basic usage of `mqdm` is to wrap a loop with a progress bar. 

## Simple sequential

```python
--8<-- "snippets/loops/simple.py"
```

<div id="cast-loops-simple" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/loops/simple.cast" data-rows="5"></div>

## Nested loops

```python
--8<-- "snippets/loops/nested.py"
```

<div id="cast-loops-nested" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/loops/nested.cast" data-rows="5"></div>

## Dynamic descriptions

```python
--8<-- "snippets/loops/dynamic_desc.py"
```

<div id="cast-loops-dynamic" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/loops/dynamic_desc.cast" data-rows="2"></div>

## Wrapping Iterators

```python
--8<-- "snippets/loops/generator.py"
```

<div id="cast-loops-generator" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/loops/generator.cast" data-rows="5"></div>

## Manual increment

```python
--8<-- "snippets/loops/manual.py"
```

<div id="cast-loops-manual" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/loops/manual.cast" data-rows="5"></div>

## Printing above the progress bars

Unfortunately, you have to print using `mqdm.print(...)` instead of the built-in `print(...)` to avoid bungling the progress bars. 

Take this up with `rich` or use logging.

```python
--8<-- "snippets/output/print.py"
```

<div id="cast-output-print" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/output/print.cast"></div>

## Logging
```python
--8<-- "snippets/output/log.py"
```

<div id="cast-output-logging" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/output/log.cast"></div>

## Hide tiny inner loops

```python
--8<-- "snippets/patterns/hide_tiny_inner_loops.py"
```

<div id="cast-patterns-hide" class="asciinema-player mqdm-cast" data-cast-src="../../assets/casts/patterns/hide_tiny_inner_loops.cast"></div>
