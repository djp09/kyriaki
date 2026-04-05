import httpx

BASE_URL = "http://localhost:8000/api"
TIMEOUT = 30.0


async def _request(method: str, path: str, **kwargs) -> dict:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        resp = await client.request(method, path, **kwargs)
        if resp.status_code == 429:
            raise Exception("Too many requests. Please wait a moment and try again.")
        if resp.status_code >= 500:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("detail") or body.get("message") or ""
            except Exception:
                pass
            raise Exception(detail or "The server encountered an error. Please try again.")
        if not resp.is_success:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("detail") or body.get("message") or ""
                if not isinstance(detail, str):
                    detail = str(detail)
            except Exception:
                pass
            raise Exception(detail or f"Request failed ({resp.status_code}).")
        return resp.json()


async def start_match(patient: dict, max_results: int = 10) -> dict:
    return await _request(
        "POST",
        "/agents/match",
        json={"patient": patient, "max_results": max_results},
    )


async def start_dossier(matching_task_id: str, nct_id: str) -> dict:
    return await _request(
        "POST",
        "/agents/dossier",
        json={"matching_task_id": matching_task_id, "nct_id": nct_id},
    )


async def get_task(task_id: str) -> dict:
    return await _request("GET", f"/agents/tasks/{task_id}")


async def list_tasks() -> list:
    return await _request("GET", "/agents/tasks")


async def resolve_gate(
    gate_id: str,
    status: str,
    resolved_by: str,
    notes: str = "",
    chain_to_trial: str = "",
) -> dict:
    body: dict = {"status": status, "resolved_by": resolved_by, "notes": notes}
    if chain_to_trial:
        body["chain_to_trial"] = chain_to_trial
    return await _request("POST", f"/agents/gates/{gate_id}/resolve", json=body)


async def upload_document(file_bytes: bytes, filename: str) -> dict:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        resp = await client.post(
            "/upload/document",
            files={"file": (filename, file_bytes)},
        )
        if not resp.is_success:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("detail") or body.get("message") or ""
            except Exception:
                pass
            raise Exception(detail or f"Upload failed ({resp.status_code}).")
        return resp.json()


async def get_trial_detail(nct_id: str) -> dict:
    return await _request("GET", f"/trials/{nct_id}")
