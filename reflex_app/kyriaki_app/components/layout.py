import reflex as rx

from ..states.navigation_state import NavigationState
from ..states.match_state import MatchState


def header() -> rx.Component:
    return rx.el.header(
        rx.el.div(
            rx.el.div(
                rx.el.h1(
                    "Kyriaki",
                    class_name="text-3xl font-bold tracking-tight text-white font-['Outfit']",
                ),
                rx.el.div(
                    rx.el.svg(
                        rx.el.svg.circle(
                            cx="32", cy="32", r="29",
                            fill="none", stroke="currentColor", stroke_width="2.2",
                        ),
                        rx.el.svg.ellipse(
                            cx="32", cy="32", rx="29", ry="10",
                            fill="none", stroke="currentColor", stroke_width="1.5",
                        ),
                        rx.el.svg.ellipse(
                            cx="32", cy="32", rx="10", ry="29",
                            fill="none", stroke="currentColor", stroke_width="1.5",
                        ),
                        rx.el.svg.text(
                            "K",
                            x="32", y="33",
                            text_anchor="middle", dominant_baseline="central",
                            font_family="Outfit, system-ui, sans-serif",
                            font_weight="800", font_size="22",
                            fill="#a78bfa",
                            letter_spacing="-0.5",
                        ),
                        view_box="0 0 64 64",
                        width="48",
                        height="48",
                        class_name="text-zinc-400",
                    ),
                ),
                class_name="flex items-center gap-3",
            ),
            rx.el.p(
                "Clinical trial matching, powered by AI",
                class_name="text-sm text-zinc-400 mt-1 font-['DM_Sans']",
            ),
            class_name="max-w-4xl mx-auto px-6 py-8 text-center flex flex-col items-center gap-2",
        ),
        class_name="header-gradient-bg",
    )


def error_banner() -> rx.Component:
    return rx.cond(
        NavigationState.error_message != "",
        rx.el.div(
            rx.el.div(
                rx.icon("circle-x", class_name="h-5 w-5 text-red-500 shrink-0"),
                rx.el.div(
                    rx.el.strong("Something went wrong", class_name="text-sm font-semibold text-red-800"),
                    rx.el.span(
                        NavigationState.error_message,
                        class_name="text-sm text-red-700",
                    ),
                    class_name="flex flex-col gap-0.5",
                ),
                class_name="flex items-start gap-3 flex-1",
            ),
            rx.el.button(
                "Dismiss",
                on_click=NavigationState.clear_error,
                class_name="text-sm text-red-600 hover:text-red-800 font-medium px-3 py-1 rounded-lg border border-red-200 hover:bg-red-50 transition-colors",
            ),
            class_name="max-w-4xl mx-auto mt-4 px-4 py-3 bg-red-50 border border-red-200 rounded-xl flex items-center justify-between gap-4 mx-4 sm:mx-auto fade-in",
        ),
        rx.fragment(),
    )


def agent_badge() -> rx.Component:
    return rx.cond(
        (NavigationState.active_agent != "") & (NavigationState.view != "loading"),
        rx.el.div(
            rx.el.span(class_name="agent-dot"),
            rx.el.span(
                NavigationState.active_agent,
                class_name="font-medium",
            ),
            " running — processing...",
            class_name="text-sm text-violet-700 bg-violet-50 border border-violet-200 rounded-full px-4 py-1.5 flex items-center gap-2 w-fit mx-auto mt-4 fade-in",
        ),
        rx.fragment(),
    )
