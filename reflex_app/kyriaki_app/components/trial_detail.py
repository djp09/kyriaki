import reflex as rx

from ..states.pipeline_state import PipelineState


def criterion_item(criterion: dict) -> rx.Component:
    status = criterion.get("status", "").to(str)
    return rx.el.div(
        rx.cond(
            (status == "MET") | (status == "NOT_TRIGGERED"),
            rx.icon("check", class_name="h-4 w-4 text-emerald-500 shrink-0 mt-0.5"),
            rx.cond(
                (status == "NOT_MET") | (status == "TRIGGERED"),
                rx.icon("x", class_name="h-4 w-4 text-red-500 shrink-0 mt-0.5"),
                rx.icon("circle-help", class_name="h-4 w-4 text-zinc-400 shrink-0 mt-0.5"),
            ),
        ),
        rx.el.div(
            rx.el.p(
                criterion.get("criterion", "").to(str),
                class_name="text-sm text-zinc-800",
            ),
            rx.cond(
                criterion.contains("explanation"),
                rx.el.p(
                    criterion["explanation"].to(str),
                    class_name="text-xs text-zinc-500 mt-0.5",
                ),
                rx.fragment(),
            ),
        ),
        class_name="flex items-start gap-2 py-2 border-b border-zinc-50 last:border-0",
    )


def flag_item(flag: str) -> rx.Component:
    return rx.el.div(
        rx.icon("triangle-alert", class_name="h-3.5 w-3.5 text-amber-500 shrink-0 mt-0.5"),
        rx.el.p(flag, class_name="text-sm text-zinc-700"),
        class_name="flex items-start gap-2",
    )


def trial_detail() -> rx.Component:
    trial = PipelineState.selected_trial
    return rx.el.div(
        rx.el.button(
            rx.icon("arrow-left", class_name="h-4 w-4"),
            "Back to results",
            on_click=PipelineState.back_to_results,
            class_name="flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-700 font-medium transition-colors mb-4",
        ),
        rx.el.div(
            rx.el.div(
                rx.el.h2(
                    trial["brief_title"].to(str),
                    class_name="text-lg font-semibold text-zinc-800",
                ),
                rx.el.div(
                    rx.el.span(trial["nct_id"].to(str), class_name="text-xs text-zinc-400 font-mono"),
                    rx.cond(
                        trial.contains("phase"),
                        rx.el.span(trial["phase"].to(str), class_name="text-xs text-zinc-500 bg-zinc-100 rounded-full px-2 py-0.5"),
                        rx.fragment(),
                    ),
                    rx.cond(
                        trial.contains("overall_status"),
                        rx.el.span(trial["overall_status"].to(str), class_name="text-xs text-emerald-600 bg-emerald-50 rounded-full px-2 py-0.5"),
                        rx.fragment(),
                    ),
                    class_name="flex items-center gap-2 flex-wrap mt-2",
                ),
                class_name="mb-4",
            ),
            rx.cond(
                trial.contains("match_score"),
                rx.el.div(
                    rx.el.div(
                        rx.el.span("Match Score: ", class_name="text-sm text-zinc-600"),
                        rx.el.span(
                            trial["match_score"].to(int).to_string(),
                            class_name=rx.cond(
                                trial["match_score"].to(int) >= 70,
                                "text-lg font-bold text-emerald-600",
                                rx.cond(
                                    trial["match_score"].to(int) >= 40,
                                    "text-lg font-bold text-amber-600",
                                    "text-lg font-bold text-red-600",
                                ),
                            ),
                        ),
                        class_name="flex items-baseline gap-1",
                    ),
                    rx.cond(
                        trial.contains("match_explanation"),
                        rx.el.p(trial["match_explanation"].to(str), class_name="text-sm text-zinc-600 mt-1"),
                        rx.fragment(),
                    ),
                    class_name="bg-zinc-50 rounded-xl p-4 mb-4",
                ),
                rx.fragment(),
            ),
            rx.cond(
                trial.contains("brief_summary"),
                rx.el.div(
                    rx.el.h3("About this trial", class_name="text-sm font-semibold text-zinc-700 mb-2"),
                    rx.el.p(trial["brief_summary"].to(str), class_name="text-sm text-zinc-600"),
                    class_name="mb-4",
                ),
                rx.fragment(),
            ),
            rx.cond(
                trial.contains("interventions"),
                rx.el.div(
                    rx.el.h3("Interventions", class_name="text-sm font-semibold text-zinc-700 mb-2"),
                    rx.foreach(
                        trial["interventions"].to(list[str]),
                        lambda i: rx.el.div(
                            rx.icon("pill", class_name="h-3.5 w-3.5 text-violet-500"),
                            rx.el.span(i, class_name="text-sm text-zinc-700"),
                            class_name="flex items-center gap-2",
                        ),
                    ),
                    class_name="mb-4",
                ),
                rx.fragment(),
            ),
            rx.cond(
                trial.contains("inclusion_evaluations"),
                rx.el.div(
                    rx.el.h3("Inclusion Criteria", class_name="text-sm font-semibold text-zinc-700 mb-2"),
                    rx.foreach(
                        trial["inclusion_evaluations"].to(list[dict[str, str]]),
                        criterion_item,
                    ),
                    class_name="mb-4",
                ),
                rx.fragment(),
            ),
            rx.cond(
                trial.contains("exclusion_evaluations"),
                rx.el.div(
                    rx.el.h3("Exclusion Criteria", class_name="text-sm font-semibold text-zinc-700 mb-2"),
                    rx.foreach(
                        trial["exclusion_evaluations"].to(list[dict[str, str]]),
                        criterion_item,
                    ),
                    class_name="mb-4",
                ),
                rx.fragment(),
            ),
            rx.cond(
                trial.contains("flags_for_oncologist"),
                rx.el.div(
                    rx.el.h3(
                        rx.icon("triangle-alert", class_name="h-4 w-4 text-amber-500"),
                        "Discuss with your oncologist",
                        class_name="text-sm font-semibold text-zinc-700 mb-2 flex items-center gap-1.5",
                    ),
                    rx.foreach(
                        trial["flags_for_oncologist"].to(list[str]),
                        flag_item,
                    ),
                    class_name="bg-amber-50 border border-amber-100 rounded-xl p-4 mb-4",
                ),
                rx.fragment(),
            ),
            rx.el.a(
                rx.icon("external-link", class_name="h-3.5 w-3.5"),
                "View on ClinicalTrials.gov",
                href="https://clinicaltrials.gov/study/" + trial["nct_id"].to(str),
                target="_blank",
                rel="noopener noreferrer",
                class_name="flex items-center gap-1.5 text-sm text-violet-600 hover:text-violet-700 font-medium",
            ),
            class_name="bg-white border border-zinc-200 rounded-xl p-6",
        ),
        class_name="fade-in",
    )
