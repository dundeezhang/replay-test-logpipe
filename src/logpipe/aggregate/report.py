"""Render aggregate rows as a text table, JSON lines or CSV."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, TextIO

from logpipe.aggregate.aggregator import AggregateRow


def _columns(rows: Sequence[dict[str, Any]]) -> list[str]:
    """Union of keys across rows, in first-seen order."""
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".") if value % 1 else str(int(value))
    return str(value)


def render_table(rows: Iterable[AggregateRow], out: TextIO) -> int:
    flat = [row.to_flat_dict() for row in rows]
    if not flat:
        out.write("(no data)\n")
        return 0
    columns = _columns(flat)
    cells = [[_cell(row.get(col)) for col in columns] for row in flat]
    widths = [max(len(col), *(len(r[i]) for r in cells)) for i, col in enumerate(columns)]
    out.write("  ".join(c.ljust(w) for c, w in zip(columns, widths)).rstrip() + "\n")
    out.write("  ".join("-" * w for w in widths) + "\n")
    for row_cells in cells:
        out.write("  ".join(v.ljust(w) for v, w in zip(row_cells, widths)).rstrip() + "\n")
    return len(flat)


def write_jsonl(rows: Iterable[AggregateRow], out: TextIO, *, flush: bool = False) -> int:
    count = 0
    for row in rows:
        out.write(json.dumps(row.to_dict(), default=str) + "\n")
        if flush:
            out.flush()
        count += 1
    return count


def write_csv(rows: Iterable[AggregateRow], path: str | Path) -> int:
    """Write rows to ``path`` as CSV with one column per group/metric key."""
    fh = open(path, "w", newline="", encoding="utf-8")
    flat = [row.to_flat_dict() for row in rows]
    writer = csv.DictWriter(fh, fieldnames=_columns(flat), restval="")
    writer.writeheader()
    for row in flat:
        writer.writerow(row)
    fh.close()
    return len(flat)
