# Examples

This section is organized in the order most people naturally reach for `mqdm`.

1. `mqdm.mqdm(xs)`
2. `mqdm.pool(process_fn, xs)`
3. a few extra pool arguments
4. nicer terminal output and nested bars

If you already know `tqdm`, `multiprocessing.Pool`, or `concurrent.futures`,
that is enough context to read these pages quickly.

## The shortest possible mental model

| familiar shape | `mqdm` shape |
| --- | --- |
| `tqdm.tqdm(xs)` | `mqdm.mqdm(xs)` |
| `Pool(...).imap(...)` | `mqdm.pool(fn, xs)` |
| `as_completed(...)` | `mqdm.ipool(fn, xs, ordered_=False)` |
| manual argument tuples | `mqdm.args(...)` |

The patterns that show up most often in real code are even simpler than the
full API surface:

- `for x in mqdm.mqdm(xs): ...`
- `mqdm.pool(process_fn, xs)`
- `mqdm.pool(process_fn, xs, n_workers=3)`
- `mqdm.pool(process_fn, xs, n_workers=3, some_shared_kw=...)`

## Start with these

- [Loops](loops.md): simple iteration, nested bars, and dynamic descriptions
- [Pools](pools.md): sequential, parallel, extra arguments, and complex arguments
- [Output](output.md): printing, logging, and byte progress
- [Patterns](patterns.md): a few lower-priority patterns that are still useful
