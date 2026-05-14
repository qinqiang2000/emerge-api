import re

from app.workspace.ids import (
    new_chat_id,
    new_job_id,
    new_project_id,
)


def test_project_id_format() -> None:
    pid = new_project_id()
    assert re.match(r"^p_[a-z0-9]{12}$", pid), pid


def test_chat_id_format() -> None:
    cid = new_chat_id()
    assert re.match(r"^c_[a-z0-9]{12}$", cid), cid


def test_job_id_format() -> None:
    jid = new_job_id()
    assert re.match(r"^j_[a-z0-9]{12}$", jid), jid


def test_ids_are_unique() -> None:
    ids = {new_project_id() for _ in range(1000)}
    assert len(ids) == 1000


def test_new_prompt_id_format() -> None:
    from app.workspace.ids import new_prompt_id
    pid = new_prompt_id()
    assert re.match(r"^pr_[0-9a-z]{12}$", pid)


def test_new_model_id_format() -> None:
    from app.workspace.ids import new_model_id
    mid = new_model_id()
    assert re.match(r"^m_[0-9a-z]{12}$", mid)


def test_new_prompt_id_unique() -> None:
    from app.workspace.ids import new_prompt_id
    ids = {new_prompt_id() for _ in range(50)}
    assert len(ids) == 50
