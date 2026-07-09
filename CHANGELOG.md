# Changelog

## 2.0.0

`mqdm 2.0.0` is a cleanup and stabilization release over `1.2.3`.

Most users who stick to the main surface:

- `mqdm.mqdm(...)`
- `mqdm.pool(...)`
- `mqdm.ipool(...)`
- `mqdm.args(...)`
- `mqdm.print(...)`

should see better behavior in nested, threaded, and multiprocess workloads without needing to rewrite normal calling code.

### Highlights

- Progress state is now owned by an explicit `Runtime`, which makes nested bars, worker output, logging, and custom runtime isolation much more predictable.
- Pool behavior is more robust around streaming, ordered results, cancellation, and aggregated failures.
- Logging and warnings integrate more cleanly with active progress displays, including worker-aware routing and cleaner teardown.
- The project now has a proper docs site under `docs/` with examples, API reference, and recorded terminal demos.

### Breaking Changes

#### Progress-level configuration moved from bars to runtimes

In `1.2.3`, `mqdm.mqdm(...)` accepted options such as:

- `progress_kw`
- `auto_refresh`
- `refresh_per_second`
- `speed_estimate_period`
- `redirect_stdout`
- `redirect_stderr`
- `expand`

In practice those settings were shared by the single live progress instance anyway, so `2.0.0` makes that explicit.

Use one of these patterns instead:

```python
import mqdm as M

M.configure(refresh_per_second=12, expand=True)

for x in M.mqdm(range(10)):
    ...
```

or:

```python
import mqdm as M

runtime = M.Runtime(refresh_per_second=12, expand=True)

for x in M.mqdm(range(10), runtime=runtime):
    ...
```

If you were not setting progress-instance options directly on `mqdm(...)`, you likely do not need to change anything.

#### The package surface is smaller and more opinionated

`2.0.0` leans harder into the main public shapes:

- `mqdm.mqdm`
- `mqdm.pool`
- `mqdm.ipool`

Older compatibility aliases and global-style internals are no longer the center of the package. If you were importing niche top-level aliases or reaching into module globals, expect to update that code.

### Added

#### Explicit runtime configuration

New runtime-centered APIs make it easier to isolate progress, logging, and worker behavior:

- `mqdm.Runtime(...)`
- `mqdm.configure(...)`

This matters most for advanced applications, tests, notebooks, and tools that want separate progress/logging domains.

#### `ipool(..., as_result_=True)`

`ipool` can now yield structured result objects instead of bare return values.

That is useful when you want the input identity, output, and error in one stream:

```python
for result in mqdm.ipool(work, items, as_result_=True, ordered_=False):
    if result.ok:
        ...
    else:
        ...
```

#### Runtime event context

Worker and task context now travels through runtime-managed events, which improves:

- worker-aware logging
- worker-safe printing
- external event sinks and dashboards
- correlation between pool tasks and emitted output

Most users will just notice that output from threaded and multiprocess work is easier to reason about.

#### New documentation site

The repo now includes a full docs site with:

- getting-started documentation
- example-driven guides
- API reference pages
- recorded terminal demos

The old README is now much shorter and points people to `docs/`.

### Improved

#### Pool execution semantics

`pool` and `ipool` were substantially reworked for better behavior in real workloads:

- ordered and unordered result handling is clearer
- generator inputs stream more naturally instead of being over-submitted up front
- `on_error='finish'` now raises after completing submitted work, while still surfacing successful results first
- ordered cancellation no longer waits unnecessarily behind slow earlier tasks
- small workloads squeeze down to sequential execution more predictably

These changes are aimed at making `mqdm.pool(...)` feel like a stronger default replacement for hand-written `concurrent.futures` loops.

#### Nested bar lifecycle and fast-loop updates

Bar open/close, detach/reattach, and fast update paths were cleaned up so that:

- detached bars preserve task state more reliably
- buffered fast updates flush correctly on close
- dynamic descriptions behave more consistently
- disabled bars still keep accurate local counts

#### Logging and warnings integration

Logging support is more robust and more runtime-aware:

- repeated installation is idempotent
- handlers are tied to the owning runtime
- warning capture can be process-only or explicit
- worker installs replay runtime logging configuration correctly
- runtime teardown now cleans up logging state

If you already use `mqdm.install_logging()`, this release should mostly feel more predictable rather than different.

#### Process and proxy rendering

Multiprocess rendering got a substantial cleanup:

- task snapshots restore more task metadata
- proxy rendering caches static state more efficiently
- live mirrors update from shared state rather than rebuilding everything each frame
- manager startup failure handling is safer

This mostly shows up as smoother behavior in process pool use and in tools built on top of `mqdm` events.

### Fixed

- Several progress speed and refresh regressions in tight loops.
- Edge cases around reopening and restoring bars from serialized task state.
- File progress tracking for `fopen(...)`, including correct byte tracking in text mode.
- Logging cleanup and warning-capture teardown edge cases.
- Compatibility behavior for process-pool helpers across Python versions.
- A range of examples, tests, and docs mismatches.

### Migration Notes

#### If you only use `mqdm(...)` in local loops

You probably do not need to change anything.

#### If you use `pool(...)` or `ipool(...)`

You probably do not need to change your call sites, but you may notice:

- better ordering behavior
- better cancellation behavior
- different failure timing for `on_error='finish'`
- the new optional `as_result_=True` mode

#### If you configured rendering on each bar

Move that configuration to either:

- `mqdm.configure(...)` for the implicit global runtime
- `mqdm.Runtime(...)` for an explicit runtime

#### If you rely on internals

If your code touched package globals, proxy internals, or older top-level aliases, expect some breakage. `2.0.0` intentionally centers the supported API around the small public surface instead of the previous global implementation details.

### Documentation

Start with:

- [README.md](/opt/gh/mqdm/README.md)
- [docs/index.md](/opt/gh/mqdm/docs/index.md)
- [docs/api.md](/opt/gh/mqdm/docs/api.md)
