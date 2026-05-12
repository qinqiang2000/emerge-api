import secrets


def _new(prefix: str) -> str:
    # 12 chars of base36 from 60 bits of entropy
    n = secrets.randbits(60)
    s = ""
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    for _ in range(12):
        s = alphabet[n % 36] + s
        n //= 36
    return f"{prefix}_{s}"


def new_project_id() -> str:
    return _new("p")


def new_doc_id() -> str:
    return _new("d")


def new_chat_id() -> str:
    return _new("c")


def new_job_id() -> str:
    return _new("j")


def new_prompt_id() -> str:
    return _new("pr")


def new_model_id() -> str:
    return _new("m")
