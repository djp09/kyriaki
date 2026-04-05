import reflex as rx

from ..states.match_state import MatchState
from ..states.navigation_state import NavigationState


def loading_view() -> rx.Component:
    return rx.el.div(
        rx.el.h2(
            "Searching for your matches",
            class_name="text-xl font-semibold text-zinc-800 font-['Outfit'] text-center",
        ),
        rx.el.div(
            rx.el.span(class_name="agent-dot"),
            rx.el.span(
                NavigationState.active_agent,
                class_name="font-medium",
            ),
            " running",
            class_name="text-sm text-violet-700 bg-violet-50 border border-violet-200 rounded-full px-4 py-1.5 flex items-center gap-2 w-fit mx-auto mt-3",
        ),
        rx.el.div(
            rx.el.div(class_name="spinner-ring"),
            rx.el.div(class_name="spinner-ring-2"),
            class_name="relative w-16 h-16 mx-auto mt-8",
        ),
        rx.el.p(
            MatchState.loading_message,
            class_name="text-sm text-zinc-600 text-center mt-6 fade-in",
        ),
        rx.el.div(
            rx.el.div(
                class_name="h-1 bg-violet-500 rounded-full progress-indeterminate w-1/4",
            ),
            class_name="w-64 mx-auto mt-4 bg-zinc-200 rounded-full overflow-hidden h-1",
        ),
        rx.el.p(
            "This typically takes 1-2 minutes as we analyze each trial's criteria",
            class_name="text-xs text-zinc-400 text-center mt-4",
        ),
        class_name="max-w-md mx-auto py-12 fade-in",
    )
