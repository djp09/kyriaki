import asyncio
import json

import reflex as rx


def _empty_pipeline() -> dict[str, str]:
    return {
        "nct_id": "",
        "dossier_task_id": "",
        "dossier_status": "",
        "dossier_data": "",
        "gate_id": "",
        "approval_status": "",
        "enrollment_task_id": "",
        "enrollment_status": "",
        "enrollment_data": "",
        "enrollment_gate_id": "",
        "outreach_task_id": "",
        "outreach_status": "",
        "outreach_data": "",
    }


def _flatten_dict(data: dict) -> dict[str, str]:
    flat: dict[str, str] = {}
    for k, v in data.items():
        if isinstance(v, (list, dict)):
            flat[k] = json.dumps(v)
        elif v is not None:
            flat[k] = str(v)
        else:
            flat[k] = ""
    return flat


def _parse_json_field(data: dict, key: str, default):
    raw = data.get(key, "")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _store_dossier(store: dict, nct_id: str, dossier: dict) -> dict:
    store = dict(store)
    sections = dossier.get("sections", [])
    if not sections and isinstance(dossier, dict):
        sections = [dossier]
    serialized = []
    for sec in sections:
        flat: dict[str, str] = {}
        for k, v in sec.items():
            if isinstance(v, (list, dict)):
                flat[k] = json.dumps(v)
            elif v is not None:
                flat[k] = str(v)
            else:
                flat[k] = ""
        serialized.append(flat)
    top_summary = dossier.get("patient_summary", "")
    if top_summary and serialized:
        serialized[0].setdefault("dossier_patient_summary", str(top_summary))
    store[nct_id] = serialized
    return store


class PipelineState(rx.State):
    pipelines: dict[str, dict[str, str]] = {}
    selected_trial: dict[str, str] = {}
    viewing_dossier_nct_id: str = ""
    viewing_enrollment_nct_id: str = ""
    viewing_outreach_nct_id: str = ""
    dossier_data_store: dict[str, list[dict[str, str]]] = {}
    enrollment_data_store: dict[str, dict[str, str]] = {}
    outreach_data_store: dict[str, dict[str, str]] = {}

    def _reset_state(self):
        self.pipelines = {}
        self.selected_trial = {}
        self.viewing_dossier_nct_id = ""
        self.viewing_enrollment_nct_id = ""
        self.viewing_outreach_nct_id = ""
        self.dossier_data_store = {}
        self.enrollment_data_store = {}
        self.outreach_data_store = {}

    def _update_pipeline(self, nct_id: str, updates: dict):
        updated = dict(self.pipelines)
        existing = dict(updated.get(nct_id, _empty_pipeline()))
        existing.update(updates)
        existing["nct_id"] = nct_id
        updated[nct_id] = existing
        self.pipelines = updated

    @rx.var
    def current_dossier_sections(self) -> list[dict[str, str]]:
        if not self.viewing_dossier_nct_id:
            return []
        return self.dossier_data_store.get(self.viewing_dossier_nct_id, [])

    @rx.var
    def current_dossier_patient_summary(self) -> str:
        sections = self.current_dossier_sections
        if sections:
            return sections[0].get("dossier_patient_summary", "")
        return ""

    @rx.var
    def current_dossier_criteria(self) -> list[dict[str, str]]:
        sections = self.current_dossier_sections
        if not sections:
            return []
        raw = sections[0].get("criteria_analysis", "[]")
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    @rx.var
    def current_dossier_next_steps(self) -> list[str]:
        sections = self.current_dossier_sections
        if not sections:
            return []
        raw = sections[0].get("next_steps", "[]")
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(s) for s in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    @rx.var
    def current_dossier_flags(self) -> list[str]:
        sections = self.current_dossier_sections
        if not sections:
            return []
        raw = sections[0].get("flags", "[]")
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(s) for s in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    @rx.var
    def current_enrollment_data(self) -> dict[str, str]:
        if not self.viewing_enrollment_nct_id:
            return {}
        return self.enrollment_data_store.get(self.viewing_enrollment_nct_id, {})

    @rx.var
    def current_enrollment_trial_title(self) -> str:
        return self.current_enrollment_data.get("trial_title", "")

    @rx.var
    def current_patient_packet(self) -> dict[str, str]:
        raw = self.current_enrollment_data.get("patient_packet", "")
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                flat: dict[str, str] = {}
                for k, v in parsed.items():
                    if isinstance(v, (list, dict)):
                        flat[k] = json.dumps(v)
                    elif v is not None:
                        flat[k] = str(v)
                    else:
                        flat[k] = ""
                return flat
        except (json.JSONDecodeError, TypeError):
            pass
        return {}

    @rx.var
    def current_patient_packet_considerations(self) -> list[str]:
        raw = self.current_patient_packet.get("special_considerations", "[]")
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(s) for s in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    @rx.var
    def current_patient_packet_checklist(self) -> list[str]:
        raw = self.current_patient_packet.get("screening_checklist", "[]")
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(s) for s in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    @rx.var
    def current_prep_guide(self) -> dict[str, str]:
        raw = self.current_enrollment_data.get("patient_prep_guide", "")
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                flat: dict[str, str] = {}
                for k, v in parsed.items():
                    if isinstance(v, (list, dict)):
                        flat[k] = json.dumps(v)
                    elif v is not None:
                        flat[k] = str(v)
                    else:
                        flat[k] = ""
                return flat
        except (json.JSONDecodeError, TypeError):
            pass
        return {}

    @rx.var
    def current_prep_documents(self) -> list[str]:
        raw = self.current_prep_guide.get("documents_to_bring", "[]")
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(s) for s in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    @rx.var
    def current_prep_questions(self) -> list[str]:
        raw = self.current_prep_guide.get("questions_to_ask", "[]")
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(s) for s in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    @rx.var
    def current_prep_steps(self) -> list[str]:
        raw = self.current_prep_guide.get("how_to_prepare", "[]")
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(s) for s in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    @rx.var
    def current_outreach_draft(self) -> dict[str, str]:
        raw = self.current_enrollment_data.get("outreach_draft", "")
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {k: str(v) if v is not None else "" for k, v in parsed.items()}
        except (json.JSONDecodeError, TypeError):
            pass
        return {}

    @rx.var
    def current_outreach_data(self) -> dict[str, str]:
        if not self.viewing_outreach_nct_id:
            return {}
        return self.outreach_data_store.get(self.viewing_outreach_nct_id, {})

    @rx.var
    def current_outreach_message(self) -> str:
        return self.current_outreach_data.get("final_message", "")

    @rx.var
    def current_outreach_subject(self) -> str:
        return self.current_outreach_data.get("subject_line", "")

    @rx.var
    def current_outreach_contacts(self) -> list[dict[str, str]]:
        raw = self.current_outreach_data.get("contacts", "[]")
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [{k: str(v) if v is not None else "" for k, v in c.items()} for c in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    @rx.event
    async def view_enrollment(self, nct_id: str):
        self.viewing_enrollment_nct_id = nct_id
        from .navigation_state import NavigationState
        nav = await self.get_state(NavigationState)
        nav.view = "enrollment"

    @rx.event
    async def view_outreach(self, nct_id: str):
        self.viewing_outreach_nct_id = nct_id
        from .navigation_state import NavigationState
        nav = await self.get_state(NavigationState)
        nav.view = "outreach"

    @rx.event
    async def select_trial(self, trial: dict):
        self.selected_trial = trial
        from .navigation_state import NavigationState
        nav = await self.get_state(NavigationState)
        nav.view = "detail"

    @rx.event
    async def back_to_results(self):
        self.selected_trial = {}
        self.viewing_dossier_nct_id = ""
        self.viewing_enrollment_nct_id = ""
        self.viewing_outreach_nct_id = ""
        from .navigation_state import NavigationState
        nav = await self.get_state(NavigationState)
        nav.view = "results"

    @rx.event
    async def analyze_trial(self, nct_id: str):
        from .match_state import MatchState
        match_state = await self.get_state(MatchState)
        task_id = match_state.results_task_id
        if not task_id:
            return
        self._update_pipeline(nct_id, {"dossier_status": "loading"})
        from .navigation_state import NavigationState
        nav = await self.get_state(NavigationState)
        nav.active_agent = "DossierAgent"
        yield
        try:
            from ..api_client import start_dossier
            task = await start_dossier(task_id, nct_id)
            status = task.get("status", "")
            if status in ("completed", "blocked") and task.get("output_data"):
                dossier = task["output_data"].get("dossier")
                gate_id = ""
                gates = task.get("gates", [])
                if gates:
                    gate_id = gates[0].get("gate_id", "")
                self._update_pipeline(nct_id, {
                    "dossier_status": "done",
                    "gate_id": gate_id,
                    "dossier_task_id": "",
                })
                if dossier:
                    self.dossier_data_store = _store_dossier(
                        self.dossier_data_store, nct_id, dossier
                    )
                nav.active_agent = ""
            else:
                self._update_pipeline(nct_id, {"dossier_task_id": task.get("task_id", "")})
                yield PipelineState.poll_dossier_task(nct_id)
        except Exception as e:
            self._update_pipeline(nct_id, {"dossier_status": "error"})
            nav.error_message = f"Analysis failed: {e}"
            nav.active_agent = ""

    @rx.event(background=True)
    async def poll_dossier_task(self, nct_id: str):
        while True:
            await asyncio.sleep(2.5)
            async with self:
                pipeline = self.pipelines.get(nct_id, {})
                task_id = pipeline.get("dossier_task_id", "")
                if not task_id:
                    return
            try:
                from ..api_client import get_task
                task = await get_task(task_id)
            except Exception:
                continue
            async with self:
                status = task.get("status", "")
                if status in ("completed", "blocked", "failed"):
                    from .navigation_state import NavigationState
                    nav = await self.get_state(NavigationState)
                    if status == "failed":
                        self._update_pipeline(nct_id, {"dossier_status": "error", "dossier_task_id": ""})
                    else:
                        dossier = task.get("output_data", {}).get("dossier")
                        gate_id = ""
                        gates = task.get("gates", [])
                        if gates:
                            gate_id = gates[0].get("gate_id", "")
                        self._update_pipeline(nct_id, {
                            "dossier_status": "done",
                            "gate_id": gate_id,
                            "dossier_task_id": "",
                        })
                        if dossier:
                            self.dossier_data_store = _store_dossier(
                                self.dossier_data_store, nct_id, dossier
                            )
                    nav.active_agent = ""
                    return

    @rx.event
    async def view_dossier(self, nct_id: str):
        pipeline = self.pipelines.get(nct_id, {})
        if pipeline.get("dossier_status") == "done" and nct_id in self.dossier_data_store:
            self.viewing_dossier_nct_id = nct_id
            from .navigation_state import NavigationState
            nav = await self.get_state(NavigationState)
            nav.view = "dossier"

    @rx.event
    async def proceed_to_enrollment(self, nct_id: str):
        pipeline = self.pipelines.get(nct_id, {})
        gate_id = pipeline.get("gate_id", "")
        if not gate_id:
            return
        self._update_pipeline(nct_id, {"approval_status": "approving"})
        yield
        try:
            from ..api_client import resolve_gate
            await resolve_gate(gate_id, "approved", "Navigator", "Proceed to enrollment", nct_id)
            self._update_pipeline(nct_id, {"approval_status": "approved", "enrollment_status": "loading"})
            from .navigation_state import NavigationState
            nav = await self.get_state(NavigationState)
            nav.active_agent = "EnrollmentAgent"
            yield
            await asyncio.sleep(2)
            try:
                from ..api_client import list_tasks
                tasks = await list_tasks()
                enroll_task = None
                for t in tasks:
                    if t.get("agent_type") == "enrollment" and t.get("status") not in ("completed", "failed"):
                        enroll_task = t
                        break
                if enroll_task:
                    self._update_pipeline(nct_id, {"enrollment_task_id": enroll_task["task_id"]})
                    yield PipelineState.poll_enrollment_task(nct_id)
            except Exception:
                pass
        except Exception as e:
            self._update_pipeline(nct_id, {"approval_status": ""})
            from .navigation_state import NavigationState
            nav = await self.get_state(NavigationState)
            nav.error_message = f"Failed to proceed: {e}"

    @rx.event(background=True)
    async def poll_enrollment_task(self, nct_id: str):
        while True:
            await asyncio.sleep(2.5)
            async with self:
                pipeline = self.pipelines.get(nct_id, {})
                task_id = pipeline.get("enrollment_task_id", "")
                if not task_id:
                    return
            try:
                from ..api_client import get_task
                task = await get_task(task_id)
            except Exception:
                continue
            async with self:
                status = task.get("status", "")
                if status in ("completed", "blocked", "failed"):
                    if status == "failed":
                        self._update_pipeline(nct_id, {"enrollment_status": "error", "enrollment_task_id": ""})
                    else:
                        gate_id = ""
                        gates = task.get("gates", [])
                        if gates:
                            gate_id = gates[0].get("gate_id", "")
                        self._update_pipeline(nct_id, {
                            "enrollment_status": "done",
                            "enrollment_gate_id": gate_id,
                            "enrollment_task_id": "",
                        })
                        out = task.get("output_data", {})
                        if out:
                            store = dict(self.enrollment_data_store)
                            store[nct_id] = _flatten_dict(out)
                            self.enrollment_data_store = store
                    from .navigation_state import NavigationState
                    nav = await self.get_state(NavigationState)
                    nav.active_agent = ""
                    return

    @rx.event
    async def approve_enrollment(self, nct_id: str):
        pipeline = self.pipelines.get(nct_id, {})
        gate_id = pipeline.get("enrollment_gate_id", "")
        if not gate_id:
            return
        try:
            from ..api_client import resolve_gate
            await resolve_gate(gate_id, "approved", "Navigator", "Packet approved, proceed with outreach")
            self._update_pipeline(nct_id, {"enrollment_status": "approved", "outreach_status": "loading"})
            from .navigation_state import NavigationState
            nav = await self.get_state(NavigationState)
            nav.active_agent = "OutreachAgent"
            yield
            await asyncio.sleep(2)
            try:
                from ..api_client import list_tasks
                tasks = await list_tasks()
                out_task = None
                for t in tasks:
                    if t.get("agent_type") == "outreach" and t.get("status") not in ("completed", "failed"):
                        out_task = t
                        break
                if out_task:
                    self._update_pipeline(nct_id, {"outreach_task_id": out_task["task_id"]})
                    yield PipelineState.poll_outreach_task(nct_id)
            except Exception:
                pass
        except Exception as e:
            from .navigation_state import NavigationState
            nav = await self.get_state(NavigationState)
            nav.error_message = f"Failed to approve enrollment: {e}"

    @rx.event(background=True)
    async def poll_outreach_task(self, nct_id: str):
        while True:
            await asyncio.sleep(2.5)
            async with self:
                pipeline = self.pipelines.get(nct_id, {})
                task_id = pipeline.get("outreach_task_id", "")
                if not task_id:
                    return
            try:
                from ..api_client import get_task
                task = await get_task(task_id)
            except Exception:
                continue
            async with self:
                status = task.get("status", "")
                if status in ("completed", "blocked", "failed"):
                    if status == "failed":
                        self._update_pipeline(nct_id, {"outreach_status": "error", "outreach_task_id": ""})
                    else:
                        self._update_pipeline(nct_id, {"outreach_status": "done", "outreach_task_id": ""})
                        out = task.get("output_data", {})
                        if out:
                            store = dict(self.outreach_data_store)
                            store[nct_id] = _flatten_dict(out)
                            self.outreach_data_store = store
                    from .navigation_state import NavigationState
                    nav = await self.get_state(NavigationState)
                    nav.active_agent = ""
                    return
