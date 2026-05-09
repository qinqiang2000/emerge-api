"""Cross-route safety helpers."""
import re

from fastapi import HTTPException


_PROJECT_ID = re.compile(r"^p_[a-z0-9]{12}$")
_DOC_ID = re.compile(r"^d_[a-z0-9]{12}$")
_JOB_ID = re.compile(r"^j_[a-z0-9]{12}$")


def safe_project_id(project_id: str) -> str:
    if not _PROJECT_ID.match(project_id):
        raise HTTPException(status_code=400, detail="invalid project_id")
    return project_id


def safe_doc_id(doc_id: str) -> str:
    if not _DOC_ID.match(doc_id):
        raise HTTPException(status_code=400, detail="invalid doc_id")
    return doc_id


def safe_job_id(job_id: str) -> str:
    if not _JOB_ID.match(job_id):
        raise HTTPException(status_code=400, detail="invalid job_id")
    return job_id
