import re

from app.workspace.ids import (
    new_project_id,
    new_doc_id,
    new_chat_id,
    new_job_id,
)


def test_project_id_format() -> None:
    pid = new_project_id()
    assert re.match(r"^p_[a-z0-9]{12}$", pid), pid


def test_doc_id_format() -> None:
    did = new_doc_id()
    assert re.match(r"^d_[a-z0-9]{12}$", did), did


def test_chat_id_format() -> None:
    cid = new_chat_id()
    assert re.match(r"^c_[a-z0-9]{12}$", cid), cid


def test_job_id_format() -> None:
    jid = new_job_id()
    assert re.match(r"^j_[a-z0-9]{12}$", jid), jid


def test_ids_are_unique() -> None:
    ids = {new_project_id() for _ in range(1000)}
    assert len(ids) == 1000
