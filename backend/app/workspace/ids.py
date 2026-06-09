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


def new_chat_id() -> str:
    return _new("c")


def new_job_id() -> str:
    return _new("j")


def new_prompt_id() -> str:
    return _new("pr")


def new_model_id() -> str:
    return _new("m")


def new_experiment_id() -> str:
    return _new("ex")


def new_published_id() -> str:
    return _new("pub")


def new_user_id() -> str:
    return _new("u")


def new_team_id() -> str:
    return _new("t")


def new_pat_id() -> str:
    return _new("pat")


def new_match_prompt_id() -> str:
    return _new("mpr")


def new_match_run_id() -> str:
    return _new("mr")
