import reflex as rx

from ..states.match_state import MatchState
from ..states.navigation_state import NavigationState
from ..states.pipeline_state import PipelineState


def score_badge(score: rx.Var) -> rx.Component:
    return rx.el.div(
        score.to(int).to_string(),
        class_name=rx.cond(
            score.to(int) >= 70,
            "text-sm font-bold text-emerald-700 bg-emerald-100 rounded-full w-10 h-10 flex items-center justify-center shrink-0",
            rx.cond(
                score.to(int) >= 40,
                "text-sm font-bold text-amber-700 bg-amber-100 rounded-full w-10 h-10 flex items-center justify-center shrink-0",
                "text-sm font-bold text-red-700 bg-red-100 rounded-full w-10 h-10 flex items-center justify-center shrink-0",
            ),
        ),
    )


def score_label(score: rx.Var) -> rx.Component:
    return rx.cond(
        score.to(int) >= 70,
        rx.el.span("Strong match", class_name="text-xs font-medium text-emerald-600"),
        rx.cond(
            score.to(int) >= 40,
            rx.el.span("Possible match", class_name="text-xs font-medium text-amber-600"),
            rx.el.span("Low match", class_name="text-xs font-medium text-red-600"),
        ),
    )


def trial_card_actions(nct_id: rx.Var, pipeline: rx.Var) -> rx.Component:
    dossier_status = pipeline["dossier_status"].to(str)
    approval_status = pipeline["approval_status"].to(str)
    enrollment_status = pipeline["enrollment_status"].to(str)
    outreach_status = pipeline["outreach_status"].to(str)

    return rx.el.div(
        rx.cond(
            dossier_status == "",
            rx.el.button(
                rx.icon("microscope", class_name="h-3.5 w-3.5"),
                "Analyze Trial",
                on_click=PipelineState.analyze_trial(nct_id),
                class_name="flex items-center gap-1.5 text-xs font-medium text-violet-600 border border-violet-200 rounded-lg px-3 py-1.5 hover:bg-violet-50 transition-colors",
            ),
            rx.cond(
                dossier_status == "loading",
                rx.el.div(
                    rx.el.span(class_name="agent-dot"),
                    rx.el.span("Analyzing...", class_name="text-xs text-violet-600"),
                    class_name="flex items-center gap-1.5",
                ),
                rx.cond(
                    dossier_status == "done",
                    rx.el.div(
                        rx.el.button(
                            rx.icon("file-text", class_name="h-3.5 w-3.5"),
                            "View Dossier",
                            on_click=PipelineState.view_dossier(nct_id),
                            class_name="flex items-center gap-1.5 text-xs font-medium text-violet-600 border border-violet-200 rounded-lg px-3 py-1.5 hover:bg-violet-50 transition-colors",
                        ),
                        rx.cond(
                            (approval_status == "") & (enrollment_status == ""),
                            rx.el.button(
                                "Proceed to Enrollment",
                                on_click=PipelineState.proceed_to_enrollment(nct_id),
                                class_name="text-xs font-medium text-emerald-600 border border-emerald-200 rounded-lg px-3 py-1.5 hover:bg-emerald-50 transition-colors",
                            ),
                            rx.cond(
                                approval_status == "approving",
                                rx.el.span("Starting enrollment...", class_name="text-xs text-zinc-500"),
                                rx.cond(
                                    enrollment_status == "loading",
                                    rx.el.div(
                                        rx.el.span(class_name="agent-dot"),
                                        rx.el.span("Enrollment in progress...", class_name="text-xs text-violet-600"),
                                        class_name="flex items-center gap-1.5",
                                    ),
                                    rx.cond(
                                        enrollment_status == "done",
                                        rx.el.div(
                                            rx.el.button(
                                                rx.icon("package", class_name="h-3.5 w-3.5"),
                                                "View Packet",
                                                on_click=PipelineState.view_enrollment(nct_id),
                                                class_name="flex items-center gap-1.5 text-xs font-medium text-violet-600 border border-violet-200 rounded-lg px-3 py-1.5 hover:bg-violet-50 transition-colors",
                                            ),
                                            rx.el.button(
                                                "Approve & Send to Site",
                                                on_click=PipelineState.approve_enrollment(nct_id),
                                                class_name="text-xs font-medium text-emerald-600 border border-emerald-200 rounded-lg px-3 py-1.5 hover:bg-emerald-50 transition-colors",
                                            ),
                                            class_name="flex items-center gap-2",
                                        ),
                                        rx.cond(
                                            enrollment_status == "approved",
                                            rx.cond(
                                                outreach_status == "loading",
                                                rx.el.div(
                                                    rx.el.span(class_name="agent-dot"),
                                                    rx.el.span("Outreach in progress...", class_name="text-xs text-violet-600"),
                                                    class_name="flex items-center gap-1.5",
                                                ),
                                                rx.cond(
                                                    outreach_status == "done",
                                                    rx.el.div(
                                                        rx.el.button(
                                                            rx.icon("mail", class_name="h-3.5 w-3.5"),
                                                            "View Outreach",
                                                            on_click=PipelineState.view_outreach(nct_id),
                                                            class_name="flex items-center gap-1.5 text-xs font-medium text-violet-600 border border-violet-200 rounded-lg px-3 py-1.5 hover:bg-violet-50 transition-colors",
                                                        ),
                                                        rx.el.span("✓ ready", class_name="text-xs font-medium text-emerald-600"),
                                                        class_name="flex items-center gap-2",
                                                    ),
                                                    rx.el.span("Enrollment sent", class_name="text-xs text-emerald-600"),
                                                ),
                                            ),
                                            rx.fragment(),
                                        ),
                                    ),
                                ),
                            ),
                        ),
                        class_name="flex items-center gap-2 flex-wrap",
                    ),
                    rx.cond(
                        dossier_status == "error",
                        rx.el.span("Analysis failed", class_name="text-xs text-red-500"),
                        rx.fragment(),
                    ),
                ),
            ),
        ),
        class_name="mt-3 pt-3 border-t border-zinc-100",
    )


def trial_card(match: dict) -> rx.Component:
    nct_id = match["nct_id"].to(str)
    pipeline = PipelineState.pipelines.get(nct_id, {
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
    })

    return rx.el.div(
        rx.el.div(
            score_badge(match["match_score"]),
            rx.el.div(
                rx.el.h3(
                    match["brief_title"].to(str),
                    class_name="text-sm font-semibold text-zinc-800 line-clamp-2",
                ),
                rx.el.div(
                    rx.el.span(nct_id, class_name="text-xs text-zinc-400 font-mono"),
                    rx.cond(
                        match.contains("phase"),
                        rx.el.span(
                            match["phase"].to(str),
                            class_name="text-xs text-zinc-500 bg-zinc-100 rounded-full px-2 py-0.5",
                        ),
                        rx.fragment(),
                    ),
                    rx.cond(
                        match.contains("overall_status"),
                        rx.el.span(
                            match["overall_status"].to(str),
                            class_name="text-xs text-emerald-600 bg-emerald-50 rounded-full px-2 py-0.5",
                        ),
                        rx.fragment(),
                    ),
                    class_name="flex items-center gap-2 flex-wrap mt-1",
                ),
                score_label(match["match_score"]),
                class_name="flex-1 min-w-0",
            ),
            class_name="flex items-start gap-3",
        ),
        rx.cond(
            match.contains("match_explanation"),
            rx.el.p(
                match["match_explanation"].to(str),
                class_name="text-xs text-zinc-600 mt-2 line-clamp-3",
            ),
            rx.fragment(),
        ),
        rx.cond(
            match.contains("nearest_site"),
            rx.el.div(
                rx.icon("map-pin", class_name="h-3 w-3 text-zinc-400"),
                rx.el.span(
                    match["nearest_site"].to(dict[str, str]).get("city", "") + ", " + match["nearest_site"].to(dict[str, str]).get("state", ""),
                    class_name="text-xs text-zinc-500",
                ),
                rx.cond(
                    match.contains("distance_miles"),
                    rx.el.span(
                        match["distance_miles"].to(int).to_string() + " mi",
                        class_name="text-xs text-zinc-400",
                    ),
                    rx.fragment(),
                ),
                class_name="flex items-center gap-1.5 mt-2",
            ),
            rx.fragment(),
        ),
        rx.el.button(
            "View details",
            on_click=PipelineState.select_trial(match),
            class_name="text-xs text-violet-600 hover:text-violet-700 font-medium mt-2",
        ),
        trial_card_actions(nct_id, pipeline),
        class_name="bg-white border border-zinc-200 rounded-xl p-4 fade-in hover:border-zinc-300 transition-colors",
    )


def trial_results() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.button(
                rx.icon("arrow-left", class_name="h-4 w-4"),
                "Start over",
                on_click=NavigationState.start_over,
                class_name="flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-700 font-medium transition-colors",
            ),
            class_name="mb-4",
        ),
        rx.cond(
            MatchState.results_patient_summary != "",
            rx.el.div(
                rx.icon("user", class_name="h-4 w-4 text-violet-500"),
                rx.el.p(MatchState.results_patient_summary, class_name="text-sm text-zinc-700"),
                class_name="flex items-start gap-2 bg-violet-50 border border-violet-100 rounded-xl p-4 mb-4",
            ),
            rx.fragment(),
        ),
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    MatchState.results_total_screened.to_string() + " trials screened",
                    class_name="text-sm text-zinc-500",
                ),
                rx.el.span(
                    MatchState.visible_matches.length().to_string() + " matches",
                    class_name="text-sm font-medium text-violet-600",
                ),
                class_name="flex items-center gap-3",
            ),
            class_name="mb-4",
        ),
        rx.cond(
            MatchState.visible_matches.length() > 0,
            rx.el.div(
                rx.foreach(MatchState.visible_matches, trial_card),
                rx.cond(
                    MatchState.excluded_count > 0,
                    rx.el.button(
                        rx.cond(
                            MatchState.show_excluded,
                            "Hide excluded trials",
                            "Show " + MatchState.excluded_count.to_string() + " excluded trials",
                        ),
                        on_click=MatchState.toggle_excluded,
                        class_name="text-xs text-zinc-400 hover:text-zinc-600 font-medium mt-4 mx-auto block transition-colors",
                    ),
                    rx.fragment(),
                ),
                class_name="flex flex-col gap-3",
            ),
            rx.cond(
                MatchState.excluded_count > 0,
                rx.el.div(
                    rx.icon("search-x", class_name="h-10 w-10 text-zinc-300 mx-auto"),
                    rx.el.p("No eligible matches found", class_name="text-base font-medium text-zinc-600 mt-3"),
                    rx.el.p(
                        "All screened trials were excluded.",
                        class_name="text-sm text-zinc-400 mt-1",
                    ),
                    rx.el.button(
                        "Show " + MatchState.excluded_count.to_string() + " excluded trials",
                        on_click=MatchState.toggle_excluded,
                        class_name="text-xs text-violet-600 hover:text-violet-700 font-medium mt-3 transition-colors",
                    ),
                    class_name="text-center py-12",
                ),
                rx.el.div(
                    rx.icon("search-x", class_name="h-10 w-10 text-zinc-300 mx-auto"),
                    rx.el.p("No matches found", class_name="text-base font-medium text-zinc-600 mt-3"),
                    rx.el.p(
                        "Try broadening your search criteria or increasing your travel distance.",
                        class_name="text-sm text-zinc-400 mt-1",
                    ),
                    class_name="text-center py-12",
                ),
            ),
        ),
        rx.el.p(
            MatchState.results_disclaimer,
            class_name="text-xs text-zinc-400 mt-6 text-center italic",
        ),
        class_name="fade-in",
    )
