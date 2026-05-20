from __future__ import annotations

import json
from pathlib import Path

from app.eval.score import run_eval
from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    eval_cells_path,
    eval_dir,
    eval_matrix_path,
    eval_meta_path,
    eval_summary_path,
    predictions_draft_dir,
)


async def test_eval_e2e_mixed_normalize_cases(workspace: Path) -> None:
    """End-to-end: 4 docs × 3 schema fields with mixed states. Verifies the
    L1 normalize pipeline does not penalise number/date/whitespace drift."""
    schema = [
        SchemaField(name="invoice_no", type=FieldType.STRING, description="x"),
        SchemaField(name="total", type=FieldType.NUMBER, description="x"),
        SchemaField(name="invoice_date", type=FieldType.STRING,
                    description="x", format="date"),
    ]
    slug = (await create_project(workspace, name="e2e"))["slug"]
    await write_schema(workspace, slug, schema, reason="t", allow_structural=True)

    pdir = predictions_draft_dir(workspace, slug)
    pdir.mkdir(parents=True, exist_ok=True)

    fixtures = [
        ("doc1", "INV-1", "100", "2024-03-12", "INV-1", "100", "2024-03-12"),
        # doc2: number normalize-equivalent
        ("doc2", "INV-2", "123.10", "2024-03-13", "INV-2", "123.1", "2024-03-13"),
        # doc3: date normalize-equivalent
        ("doc3", "INV-3", "200", "2024-03-14", "INV-3", "200", "2024/3/14"),
        # doc4: amount field truly wrong
        ("doc4", "INV-4", "1000", "2024-03-15", "INV-4", "1500", "2024-03-15"),
    ]

    for stem, r_inv, r_tot, r_date, p_inv, p_tot, p_date in fixtures:
        meta = await upload_doc(
            workspace, slug, b"%PDF-1.4\n%%EOF\n", f"{stem}.pdf",
        )
        filename = meta["filename"]
        atomic_write_json(
            pdir / f"{filename}.json",
            {"entities": [{
                "invoice_no": p_inv, "total": p_tot, "invoice_date": p_date,
            }]},
        )
        await save_reviewed(
            workspace, slug, filename,
            entities=[{
                "invoice_no": r_inv, "total": r_tot, "invoice_date": r_date,
            }],
            source=ReviewedSource.MANUAL,
        )

    result = await run_eval(workspace, slug, use_llm_judge=False)

    assert result.n_reviewed == 4
    # doc1, doc2 (number normalize), doc3 (date normalize) all fully correct;
    # doc4 wrong on total. doc_accuracy = 3/4.
    assert result.doc_accuracy == 0.75

    d = eval_dir(workspace, slug, result.ts)
    assert d.exists()
    assert eval_summary_path(workspace, slug, result.ts).exists()
    assert eval_cells_path(workspace, slug, result.ts).exists()
    assert eval_matrix_path(workspace, slug, result.ts).exists()
    assert eval_meta_path(workspace, slug, result.ts).exists()

    lines = eval_cells_path(workspace, slug, result.ts).read_text().splitlines()
    cells = [json.loads(line) for line in lines]
    assert len(cells) == 4 * 3  # 4 docs × 3 fields
    normalize_count = sum(1 for c in cells if c["verdict_source"] == "normalize" and c["status"] == "correct")
    # doc2 number + doc3 date should be auto-equivalent.
    assert normalize_count == 2

    csv_text = eval_matrix_path(workspace, slug, result.ts).read_text()
    header = csv_text.splitlines()[0]
    assert "filename" in header
    assert "·truth" in header
    assert "·pred" in header
