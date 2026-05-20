from app.eval.pivot import SEP, cells_to_csv
from app.eval.types import CellVerdict
from app.schemas.schema_field import SchemaField


def _f(name: str) -> SchemaField:
    return SchemaField(name=name, type="string", description="d")


def test_single_doc_three_fields_all_correct() -> None:
    schema = [_f("a"), _f("b"), _f("c")]
    cells = [
        CellVerdict(filename="d.pdf", entity_idx=0, field="a", status="correct",
                    truth="1", pred="1", verdict_source="exact"),
        CellVerdict(filename="d.pdf", entity_idx=0, field="b", status="correct",
                    truth="2", pred="2", verdict_source="exact"),
        CellVerdict(filename="d.pdf", entity_idx=0, field="c", status="correct",
                    truth="3", pred="3", verdict_source="exact"),
    ]
    csv_text = cells_to_csv(schema, cells)
    lines = csv_text.splitlines()
    assert len(lines) == 2  # header + 1 row
    headers = lines[0].split(",")
    assert headers[:3] == ["filename", "entity_idx", "n_fields_correct"]
    assert f"a{SEP}truth" in headers
    assert f"a{SEP}pred" in headers
    row = lines[1].split(",")
    assert row[0] == "d.pdf"
    assert row[1] == "0"
    assert row[2] == "3"


def test_two_entities_two_rows() -> None:
    schema = [_f("x")]
    cells = [
        CellVerdict(filename="d.pdf", entity_idx=0, field="x", status="correct",
                    truth="a", pred="a", verdict_source="exact"),
        CellVerdict(filename="d.pdf", entity_idx=1, field="x", status="wrong",
                    truth="b", pred="c", verdict_source="normalize"),
    ]
    csv_text = cells_to_csv(schema, cells)
    lines = csv_text.splitlines()
    assert len(lines) == 3  # header + 2 rows


def test_absent_values_render_as_empty_cells() -> None:
    schema = [_f("x"), _f("y")]
    cells = [
        CellVerdict(filename="d.pdf", entity_idx=0, field="x", status="correct",
                    truth="hi", pred="hi", verdict_source="exact"),
        CellVerdict(filename="d.pdf", entity_idx=0, field="y", status="absent_both",
                    verdict_source="presence"),
    ]
    csv_text = cells_to_csv(schema, cells)
    lines = csv_text.splitlines()
    row = lines[1].split(",")
    # Header order: filename, entity_idx, n_fields_correct, x·truth, x·pred,
    # y·truth, y·pred
    assert row[3] == "hi"
    assert row[4] == "hi"
    assert row[5] == ""
    assert row[6] == ""


def test_field_name_with_underscore() -> None:
    schema = [_f("tax_id")]
    cells = [
        CellVerdict(filename="d.pdf", entity_idx=0, field="tax_id", status="correct",
                    truth="123", pred="123", verdict_source="exact"),
    ]
    csv_text = cells_to_csv(schema, cells)
    headers = csv_text.splitlines()[0]
    assert f"tax_id{SEP}truth" in headers
    assert f"tax_id{SEP}pred" in headers
