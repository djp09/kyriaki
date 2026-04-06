import asyncio

import reflex as rx

FALLBACK_MESSAGES: list[str] = [
    "Searching ClinicalTrials.gov for recruiting studies...",
    "Found potential matches. Analyzing eligibility criteria...",
    "Reviewing inclusion and exclusion criteria against your profile...",
    "Evaluating biomarker and treatment history requirements...",
    "Calculating distances to trial sites near you...",
    "Ranking trials by match confidence...",
    "Almost there -- finalizing your personalized results...",
]

DISCLAIMER: str = (
    "These results are for informational purposes only and do not constitute medical advice. "
    "Please discuss all findings with your oncologist before making any treatment decisions."
)


class MatchState(rx.State):
    match_task_id: str = ""
    results_patient_summary: str = ""
    results_matches: list[dict[str, str]] = []
    results_total_screened: int = 0
    results_task_id: str = ""
    results_disclaimer: str = DISCLAIMER
    fallback_msg_index: int = 0
    loading_message: str = FALLBACK_MESSAGES[0]
    is_loading: bool = False
    fallback_messages: list[str] = FALLBACK_MESSAGES
    show_excluded: bool = False

    @rx.event
    def toggle_excluded(self):
        self.show_excluded = not self.show_excluded

    @rx.var
    def visible_matches(self) -> list[dict[str, str]]:
        if self.show_excluded:
            return self.results_matches
        return [m for m in self.results_matches if int(m.get("match_score", 0)) > 0]

    @rx.var
    def excluded_count(self) -> int:
        return sum(1 for m in self.results_matches if int(m.get("match_score", 0)) == 0)

    def _reset_state(self):
        self.match_task_id = ""
        self.results_patient_summary = ""
        self.results_matches = []
        self.results_total_screened = 0
        self.results_task_id = ""
        self.fallback_msg_index = 0
        self.loading_message = FALLBACK_MESSAGES[0]
        self.is_loading = False
        self.show_excluded = False

    @rx.event
    async def start_match(self, patient: dict):
        from .navigation_state import NavigationState
        nav = await self.get_state(NavigationState)
        nav.view = "loading"
        nav.error_message = ""
        nav.active_agent = "MatchingAgent"
        self.is_loading = True
        self.fallback_msg_index = 0
        self.loading_message = FALLBACK_MESSAGES[0]
        from .pipeline_state import PipelineState
        pipeline = await self.get_state(PipelineState)
        pipeline._reset_state()
        yield
        try:
            from ..api_client import start_match
            task = await start_match(patient)
            if task.get("status") == "completed" and task.get("output_data"):
                out = task["output_data"]
                self.results_patient_summary = out.get("patient_summary", "")
                self.results_matches = out.get("matches", [])
                self.results_total_screened = out.get("total_trials_screened", 0)
                self.results_task_id = task.get("task_id", "")
                nav.view = "results"
                nav.active_agent = ""
                self.is_loading = False
            else:
                self.match_task_id = task.get("task_id", "")
                yield MatchState.poll_match_task
                yield MatchState.cycle_fallback_messages
        except Exception as e:
            nav.error_message = str(e)
            nav.view = nav.previous_view
            nav.active_agent = ""
            self.is_loading = False

    @rx.event(background=True)
    async def poll_match_task(self):
        while True:
            async with self:
                task_id = self.match_task_id
                if not task_id:
                    return
            try:
                from ..api_client import get_task
                task = await get_task(task_id)
            except Exception as exc:
                from ..api_client import NotFoundError
                if isinstance(exc, NotFoundError):
                    async with self:
                        from .navigation_state import NavigationState
                        nav = await self.get_state(NavigationState)
                        nav.error_message = "Task expired. Please start a new search."
                        nav.view = nav.previous_view
                        nav.active_agent = ""
                        self.match_task_id = ""
                        self.is_loading = False
                    return
                await asyncio.sleep(4)
                continue
            async with self:
                status = task.get("status", "")
                if status in ("completed", "failed", "blocked"):
                    from .navigation_state import NavigationState
                    nav = await self.get_state(NavigationState)
                    if status == "failed":
                        nav.error_message = task.get("error", "Matching failed.")
                        nav.view = nav.previous_view
                    else:
                        out = task.get("output_data", {})
                        self.results_patient_summary = out.get("patient_summary", "")
                        self.results_matches = out.get("matches", [])
                        self.results_total_screened = out.get("total_trials_screened", 0)
                        self.results_task_id = task.get("task_id", task_id)
                        nav.view = "results"
                    nav.active_agent = ""
                    self.match_task_id = ""
                    self.is_loading = False
                    return
                events = task.get("events", [])
                if events:
                    progress_events = [e for e in events if e.get("event_type") == "progress"]
                    if progress_events:
                        last = progress_events[-1]
                        data = last.get("data", last)
                        step = data.get("step", "")
                        if step == "searching_trials":
                            self.loading_message = "Searching ClinicalTrials.gov for recruiting studies..."
                        elif step == "analyzing_trial":
                            idx = data.get("trial_index", "")
                            total = data.get("total", "")
                            self.loading_message = f"Analyzing trial {idx} of {total}..."
                        elif step == "deep_analysis":
                            count = data.get("trial_count", "")
                            self.loading_message = f"Starting deep analysis of {count} trials..."
            await asyncio.sleep(2)

    @rx.event(background=True)
    async def cycle_fallback_messages(self):
        while True:
            await asyncio.sleep(4)
            async with self:
                if not self.is_loading:
                    return
                if self.fallback_msg_index < len(FALLBACK_MESSAGES) - 1:
                    self.fallback_msg_index += 1
                    self.loading_message = FALLBACK_MESSAGES[self.fallback_msg_index]
