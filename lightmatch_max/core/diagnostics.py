"""Diagnostics runner — the pure core behind the in-Max self-test. Runs a list of named
check callables, catching everything, and formats a PASS/FAIL report. The dock supplies
the actual checks (deps present, scene pull, census + warnings, apply→undo round-trip,
main-thread marshaller, optional key ping) — this module just runs them safely and
formats the result, so the whole thing is testable without Max."""

from __future__ import annotations

from typing import Callable


def run_checks(checks: list[tuple[str, Callable[[], object]]]) -> list[dict]:
    """Each check is (name, fn). fn returns a detail string/obj on success or raises on
    failure. Returns [{name, ok, detail}] — never raises."""
    results: list[dict] = []
    for name, fn in checks:
        try:
            detail = fn()
            results.append({"name": name, "ok": True, "detail": "" if detail is None else str(detail)})
        except Exception as e:  # noqa: BLE001
            results.append({"name": name, "ok": False, "detail": f"{type(e).__name__}: {e}"})
    return results


def format_report(results: list[dict]) -> str:
    lines = []
    for r in results:
        mark = "✓" if r["ok"] else "✗"
        line = f"{mark} {r['name']}"
        if r["detail"]:
            line += f" — {r['detail']}"
        lines.append(line)
    n_ok = sum(1 for r in results if r["ok"])
    header = f"Diagnostics: {n_ok}/{len(results)} checks passed"
    if n_ok == len(results):
        header += " — everything is wired; you're ready to Analyze."
    else:
        header += " — fix the ✗ items above before a real run."
    return header + "\n" + "\n".join(lines)


def all_passed(results: list[dict]) -> bool:
    return bool(results) and all(r["ok"] for r in results)
