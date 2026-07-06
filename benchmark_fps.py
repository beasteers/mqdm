#!/usr/bin/env python3
import argparse
import statistics
import time

import mqdm as M

try:
    import tqdm
except ImportError:
    tqdm = None


def _bench_vanilla_iter(*, seconds: float) -> dict:
    count = 0
    start = time.perf_counter()
    deadline = start + seconds

    for _ in range(10**9):
        count += 1
        if time.perf_counter() >= deadline:
            break

    elapsed = time.perf_counter() - start
    return {
        "count": count,
        "elapsed": elapsed,
        "fps": count / elapsed if elapsed else 0.0,
    }


def _bench_enum_iter(*, seconds: float) -> dict:
    count = 0
    start = time.perf_counter()
    deadline = start + seconds

    for _, _ in enumerate(range(10**9)):
        count += 1
        if time.perf_counter() >= deadline:
            break

    elapsed = time.perf_counter() - start
    return {
        "count": count,
        "elapsed": elapsed,
        "fps": count / elapsed if elapsed else 0.0,
    }


def _bench_enum_gen_iter(*, seconds: float) -> dict:
    count = 0
    start = time.perf_counter()
    deadline = start + seconds

    for _, _ in enumerate((x for x in range(10**9))):
        count += 1
        if time.perf_counter() >= deadline:
            break

    elapsed = time.perf_counter() - start
    return {
        "count": count,
        "elapsed": elapsed,
        "fps": count / elapsed if elapsed else 0.0,
    }


def _bench_vanilla_manual(*, seconds: float) -> dict:
    count = 0
    start = time.perf_counter()
    deadline = start + seconds

    while True:
        count += 1
        if time.perf_counter() >= deadline:
            break

    elapsed = time.perf_counter() - start
    return {
        "count": count,
        "elapsed": elapsed,
        "fps": count / elapsed if elapsed else 0.0,
    }


def _bench_tqdm_iter(*, seconds: float, disable: bool) -> dict:
    if tqdm is None:
        raise RuntimeError("tqdm is not installed")

    count = 0
    start = time.perf_counter()
    deadline = start + seconds

    for _ in tqdm.tqdm(range(10**9), disable=disable):
        count += 1
        if time.perf_counter() >= deadline:
            break

    elapsed = time.perf_counter() - start
    return {
        "count": count,
        "elapsed": elapsed,
        "fps": count / elapsed if elapsed else 0.0,
    }


def _bench_tqdm_manual(*, seconds: float, disable: bool) -> dict:
    if tqdm is None:
        raise RuntimeError("tqdm is not installed")

    count = 0
    start = time.perf_counter()
    deadline = start + seconds

    with tqdm.tqdm(total=10**9, disable=disable) as bar:
        while True:
            bar.update()
            count += 1
            if time.perf_counter() >= deadline:
                break

    elapsed = time.perf_counter() - start
    return {
        "count": count,
        "elapsed": elapsed,
        "fps": count / elapsed if elapsed else 0.0,
    }


def _bench_iter(*, seconds: float, disable: bool, fast_fps_delta: float, transient: bool) -> dict:
    count = 0
    start = time.perf_counter()
    deadline = start + seconds

    for _ in M.mqdm(
        range(10**9),
        disable=disable,
        fast_fps_delta=fast_fps_delta,
        leave=not transient,
        desc=f"iter disable={disable} delta={fast_fps_delta}",
    ):
        count += 1
        if time.perf_counter() >= deadline:
            break

    elapsed = time.perf_counter() - start
    return {
        "count": count,
        "elapsed": elapsed,
        "fps": count / elapsed if elapsed else 0.0,
    }


def _bench_manual(*, seconds: float, disable: bool, fast_fps_delta: float, transient: bool) -> dict:
    count = 0
    start = time.perf_counter()
    deadline = start + seconds

    with M.mqdm(
        total=10**9,
        disable=disable,
        fast_fps_delta=fast_fps_delta,
        leave=not transient,
        desc=f"manual disable={disable} delta={fast_fps_delta}",
    ) as bar:
        while True:
            bar.update()
            count += 1
            if time.perf_counter() >= deadline:
                break

    elapsed = time.perf_counter() - start
    return {
        "count": count,
        "elapsed": elapsed,
        "fps": count / elapsed if elapsed else 0.0,
    }


BENCHES = {
    "vanilla-iter": lambda seconds: _bench_vanilla_iter(seconds=seconds),
    "enumerate-iter": lambda seconds: _bench_enum_iter(seconds=seconds),
    "enumerate-gen-iter": lambda seconds: _bench_enum_gen_iter(seconds=seconds),
    "vanilla-manual": lambda seconds: _bench_vanilla_manual(seconds=seconds),
    "tqdm-iter-disabled": lambda seconds: _bench_tqdm_iter(seconds=seconds, disable=True),
    "tqdm-iter-enabled": lambda seconds: _bench_tqdm_iter(seconds=seconds, disable=False),
    "tqdm-manual-disabled": lambda seconds: _bench_tqdm_manual(seconds=seconds, disable=True),
    "tqdm-manual-enabled": lambda seconds: _bench_tqdm_manual(seconds=seconds, disable=False),
    "iter-disabled": lambda seconds: _bench_iter(seconds=seconds, disable=True, fast_fps_delta=0.05, transient=True),
    "iter-direct": lambda seconds: _bench_iter(seconds=seconds, disable=False, fast_fps_delta=0.0, transient=True),
    "iter-batched": lambda seconds: _bench_iter(seconds=seconds, disable=False, fast_fps_delta=0.05, transient=True),
    "manual-disabled": lambda seconds: _bench_manual(seconds=seconds, disable=True, fast_fps_delta=0.05, transient=True),
    "manual-direct": lambda seconds: _bench_manual(seconds=seconds, disable=False, fast_fps_delta=0.0, transient=True),
    "manual-batched": lambda seconds: _bench_manual(seconds=seconds, disable=False, fast_fps_delta=0.05, transient=True),
}


def _run_case(name: str, *, seconds: float, repeats: int, warmup: float) -> dict:
    bench = BENCHES[name]
    if warmup > 0:
        bench(min(seconds, warmup))

    runs = [bench(seconds) for _ in range(repeats)]
    fps_values = [run["fps"] for run in runs]
    count_values = [run["count"] for run in runs]
    elapsed_values = [run["elapsed"] for run in runs]
    return {
        "name": name,
        "fps_mean": statistics.mean(fps_values),
        "fps_min": min(fps_values),
        "fps_max": max(fps_values),
        "count_mean": statistics.mean(count_values),
        "elapsed_mean": statistics.mean(elapsed_values),
    }


def _format_int(x: float) -> str:
    return f"{int(round(x)):,}"


def _print_results(results: list[dict]) -> None:
    headers = ("benchmark", "fps(mean)", "fps(min)", "fps(max)", "iters(mean)", "sec(mean)")
    rows = [
        (
            r["name"],
            _format_int(r["fps_mean"]),
            _format_int(r["fps_min"]),
            _format_int(r["fps_max"]),
            _format_int(r["count_mean"]),
            f'{r["elapsed_mean"]:.3f}',
        )
        for r in results
    ]
    widths = [max(len(row[i]) for row in [headers, *rows]) for i in range(len(headers))]
    fmt = "  ".join(f"{{:{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for row in rows:
        print(fmt.format(*row))


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark mqdm hot-loop throughput.")
    parser.add_argument(
        "--bench",
        nargs="+",
        default=[
            "vanilla-iter",
            "enumerate-iter",
            "enumerate-gen-iter",
            "tqdm-iter-disabled",
            "tqdm-iter-enabled",
            "iter-disabled",
            "iter-batched",
            "iter-direct",
            "vanilla-manual",
            "tqdm-manual-disabled",
            "tqdm-manual-enabled",
            "manual-disabled",
            "manual-batched",
            "manual-direct",
        ],
        choices=sorted(BENCHES),
        help="Benchmark case(s) to run.",
    )
    parser.add_argument("--seconds", type=float, default=1.0, help="Duration for each measured run.")
    parser.add_argument("--repeats", type=int, default=3, help="Number of measured runs per case.")
    parser.add_argument("--warmup", type=float, default=0.25, help="Optional warmup duration before each case.")
    args = parser.parse_args()

    results = [
        _run_case(name, seconds=args.seconds, repeats=args.repeats, warmup=args.warmup)
        for name in args.bench
    ]
    _print_results(results)


if __name__ == "__main__":
    main()
