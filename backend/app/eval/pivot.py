from __future__ import annotations

import csv
import io

from app.eval.types import CellVerdict
from app.schemas.schema_field import SchemaField


SEP = "·"  # MIDDLE DOT


def cells_to_csv(schema: list[SchemaField], cells: list[CellVerdict]) -> str:
    """Pivot per-cell verdicts into wide-format CSV. One row per
    (filename, entity_idx); two columns per schema field (truth, pred);
    n_fields_correct precomputed."""
    rows: dict[tuple[str, int], dict[str, CellVerdict]] = {}
    for c in cells:
        rows.setdefault((c.filename, c.entity_idx), {})[c.field] = c

    headers = ["filename", "entity_idx", "n_fields_correct"]
    for f in schema:
        headers.append(f"{f.name}{SEP}truth")
        headers.append(f"{f.name}{SEP}pred")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for filename, entity_idx in sorted(rows.keys()):
        cell_map = rows[(filename, entity_idx)]
        n_correct = sum(1 for c in cell_map.values() if c.status == "correct")
        row: list[object] = [filename, entity_idx, n_correct]
        for f in schema:
            c = cell_map.get(f.name)
            if c is None:
                row.append("")
                row.append("")
            else:
                row.append(c.truth or "")
                row.append(c.pred or "")
        writer.writerow(row)
    return buf.getvalue()
