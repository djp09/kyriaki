import reflex as rx


class NavigationState(rx.State):
    view: str = "upload"
    previous_view: str = "upload"
    error_message: str = ""
    active_agent: str = ""

    @rx.event
    async def set_view(self, new_view: str):
        if self.view == "loading" and new_view != "loading":
            from .match_state import MatchState
            match = await self.get_state(MatchState)
            match.match_task_id = ""
            match.is_loading = False
        self.previous_view = self.view
        self.view = new_view

    @rx.event
    def set_error(self, msg: str):
        self.error_message = msg

    @rx.event
    def clear_error(self):
        self.error_message = ""

    @rx.event
    async def start_over(self):
        self.view = "upload"
        self.previous_view = "upload"
        self.error_message = ""
        self.active_agent = ""
        from .upload_state import UploadState
        upload = await self.get_state(UploadState)
        upload._reset_state()
        from .intake_state import IntakeState
        intake = await self.get_state(IntakeState)
        intake._reset_state()
        from .match_state import MatchState
        match = await self.get_state(MatchState)
        match._reset_state()
        from .pipeline_state import PipelineState
        pipeline = await self.get_state(PipelineState)
        pipeline._reset_state()
