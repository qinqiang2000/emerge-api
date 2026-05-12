import re
from pathlib import Path

from app.workspace.ids import new_experiment_id
from app.workspace.paths import (
    experiment_dir,
    experiment_extract_path,
    experiment_extracts_dir,
    experiment_meta_path,
    experiments_dir,
)


def test_new_experiment_id_format():
    eid = new_experiment_id()
    assert re.match(r"^ex_[a-z0-9]{12}$", eid), eid


def test_experiment_path_helpers(tmp_path: Path):
    ws = tmp_path
    pid = "p_test12345678"
    eid = "ex_abcdef012345"
    did = "d_doc000000000"
    assert experiments_dir(ws, pid) == ws / pid / "experiments"
    assert experiment_dir(ws, pid, eid) == ws / pid / "experiments" / eid
    assert experiment_meta_path(ws, pid, eid) == ws / pid / "experiments" / eid / "meta.json"
    assert experiment_extracts_dir(ws, pid, eid) == ws / pid / "experiments" / eid / "extracts"
    assert experiment_extract_path(ws, pid, eid, did) == \
        ws / pid / "experiments" / eid / "extracts" / f"{did}.json"
