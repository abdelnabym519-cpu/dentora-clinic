#!/usr/bin/env python3
"""Small stdlib HTTP load probe for CI/staging validation, not capacity tuning."""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


def _request(url: str, timeout: float) -> tuple[bool, float]:
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read()
            ok = 200 <= response.status < 400
    except Exception:
        ok = False
    return ok, (time.perf_counter() - start) * 1000.0


def run(url: str, requests: int, concurrency: int, timeout: float) -> dict[str, float | int]:
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_request, url, timeout) for _ in range(requests)]
        results = [future.result() for future in as_completed(futures)]
    successes = sum(1 for ok, _ in results if ok)
    latencies = sorted(latency for _, latency in results)
    index = max(0, math.ceil(0.95 * len(latencies)) - 1)
    return {
        "requests": requests,
        "successes": successes,
        "failures": requests - successes,
        "error_rate": (requests - successes) / requests,
        "p95_ms": latencies[index],
        "max_ms": max(latencies),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=1500.0)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.concurrency > args.requests:
        parser.error("require requests >= concurrency >= 1")
    result = run(args.url, args.requests, args.concurrency, args.timeout)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["error_rate"] <= args.max_error_rate and result["p95_ms"] <= args.max_p95_ms else 1


if __name__ == "__main__":
    raise SystemExit(main())
