import pytest
from pydantic import ValidationError

from app.schemas.reviewed import Reviewed, ReviewedSource


def test_reviewed_minimal() -> None:
    r = Reviewed(entities=[{"invoice_no": "INV-1"}], source=ReviewedSource.MANUAL)
    assert r.entities == [{"invoice_no": "INV-1"}]
    assert r.source == ReviewedSource.MANUAL
    assert r.notes is None


def test_reviewed_with_notes() -> None:
    r = Reviewed(
        entities=[{"buyer_name": "ACME"}],
        source=ReviewedSource.MANUAL,
        notes={"buyer_name": "official: ACME Sdn Bhd"},
    )
    assert r.notes == {"buyer_name": "official: ACME Sdn Bhd"}


def test_reviewed_source_enum_values() -> None:
    assert ReviewedSource.MANUAL.value == "manual"
    assert ReviewedSource.FEEDBACK.value == "feedback"


def test_reviewed_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Reviewed(
            entities=[{}],
            source=ReviewedSource.MANUAL,
            unknown_field="x",
        )


def test_reviewed_serializes_with_notes_alias() -> None:
    r = Reviewed(
        entities=[{}],
        source=ReviewedSource.MANUAL,
        notes={"a": "b"},
    )
    blob = r.model_dump(by_alias=True, exclude_none=True)
    # `notes` aliased to `_notes` for the wire shape
    assert "_notes" in blob
    assert blob["_notes"] == {"a": "b"}
    assert "source" in blob
