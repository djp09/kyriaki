import reflex as rx

from ..states.pipeline_state import PipelineState


def dossier_criterion(criterion: dict) -> rx.Component:
    status = criterion.get("status", "").to(str)
    return rx.el.div(
        rx.cond(
            (status == "met") | (status == "MET") | (status == "not_triggered") | (status == "NOT_TRIGGERED"),
            rx.icon("check", class_name="h-4 w-4 text-emerald-500 shrink-0 mt-0.5"),
            rx.cond(
                (status == "not_met") | (status == "NOT_MET") | (status == "triggered") | (status == "TRIGGERED"),
                rx.icon("x", class_name="h-4 w-4 text-red-500 shrink-0 mt-0.5"),
                rx.cond(
                    (status == "needs_verification") | (status == "NEEDS_VERIFICATION") | (status == "unknown"),
                    rx.icon("circle-alert", class_name="h-4 w-4 text-amber-500 shrink-0 mt-0.5"),
                    rx.icon("circle-help", class_name="h-4 w-4 text-zinc-400 shrink-0 mt-0.5"),
                ),
            ),
        ),
        rx.el.div(
            rx.el.p(
                criterion.get("criterion", "").to(str),
                class_name="text-sm text-zinc-800",
            ),
            rx.cond(
                criterion.get("evidence", "").to(str) != "",
                rx.el.p(
                    criterion["evidence"].to(str),
                    class_name="text-xs text-zinc-500 mt-0.5",
                ),
                rx.fragment(),
            ),
            rx.cond(
                criterion.get("notes", "").to(str) != "",
                rx.el.p(
                    criterion["notes"].to(str),
                    class_name="text-xs text-zinc-400 mt-0.5 italic",
                ),
                rx.fragment(),
            ),
            rx.cond(
                criterion.get("type", "").to(str) != "",
                rx.el.span(
                    criterion["type"].to(str),
                    class_name="text-xs text-zinc-400 bg-zinc-100 rounded-full px-2 py-0.5 mt-1 inline-block w-fit",
                ),
                rx.fragment(),
            ),
        ),
        class_name="flex items-start gap-2 py-2.5 border-b border-zinc-100 last:border-0",
    )


def flag_item(item: str) -> rx.Component:
    return rx.el.div(
        rx.icon("triangle-alert", class_name="h-3.5 w-3.5 text-amber-500 shrink-0 mt-0.5"),
        rx.el.p(item, class_name="text-sm text-zinc-700"),
        class_name="flex items-start gap-2",
    )


def next_step_item(item: str) -> rx.Component:
    return rx.el.div(
        rx.icon("arrow-right", class_name="h-3.5 w-3.5 text-violet-500 shrink-0 mt-0.5"),
        rx.el.p(item, class_name="text-sm text-zinc-700"),
        class_name="flex items-start gap-2",
    )


def dossier_section_card(section: dict) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.h3(
                section.get("brief_title", "").to(str),
                class_name="text-base font-semibold text-zinc-800",
            ),
            rx.el.div(
                rx.cond(
                    section.get("nct_id", "").to(str) != "",
                    rx.el.span(section["nct_id"].to(str), class_name="text-xs text-zinc-400 font-mono"),
                    rx.fragment(),
                ),
                rx.cond(
                    section.get("revised_score", "").to(str) != "",
                    rx.el.span(
                        "Score: " + section["revised_score"].to(str),
                        class_name=rx.cond(
                            section["revised_score"].to(int) >= 70,
                            "text-xs font-bold text-emerald-600 bg-emerald-100 rounded-full px-2 py-0.5",
                            rx.cond(
                                section["revised_score"].to(int) >= 40,
                                "text-xs font-bold text-amber-600 bg-amber-100 rounded-full px-2 py-0.5",
                                "text-xs font-bold text-red-600 bg-red-100 rounded-full px-2 py-0.5",
                            ),
                        ),
                    ),
                    rx.fragment(),
                ),
                class_name="flex items-center gap-2 mt-1",
            ),
            class_name="mb-4",
        ),
        rx.cond(
            section.get("score_justification", "").to(str) != "",
            rx.el.div(
                rx.el.h4("Score Justification", class_name="text-sm font-semibold text-zinc-700 mb-1"),
                rx.el.p(section["score_justification"].to(str), class_name="text-sm text-zinc-600"),
                class_name="bg-zinc-50 rounded-lg p-4 mb-4",
            ),
            rx.fragment(),
        ),
        rx.cond(
            section.get("patient_summary", "").to(str) != "",
            rx.el.div(
                rx.el.h4("What This Means For You", class_name="text-sm font-semibold text-zinc-700 mb-1"),
                rx.el.p(section["patient_summary"].to(str), class_name="text-sm text-zinc-600"),
                class_name="bg-violet-50 border border-violet-100 rounded-lg p-4 mb-4",
            ),
            rx.fragment(),
        ),
        rx.cond(
            section.get("clinical_summary", "").to(str) != "",
            rx.el.div(
                rx.el.h4("Clinical Summary", class_name="text-sm font-semibold text-zinc-700 mb-1"),
                rx.el.p(section["clinical_summary"].to(str), class_name="text-sm text-zinc-600"),
                class_name="mb-4",
            ),
            rx.fragment(),
        ),
        class_name="bg-white border border-zinc-200 rounded-xl p-6 mb-4",
    )


def dossier_view() -> rx.Component:
    nct_id = PipelineState.viewing_dossier_nct_id
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
        rx.el.button(
            rx.icon("arrow-left", class_name="h-4 w-4"),
            "Back to results",
            on_click=PipelineState.back_to_results,
            class_name="flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-700 font-medium transition-colors mb-4",
        ),
        rx.el.div(
            rx.icon("file-text", class_name="h-5 w-5 text-violet-500"),
            rx.el.h2(
                "Eligibility Dossier",
                class_name="text-xl font-semibold text-zinc-800 font-['Outfit']",
            ),
            class_name="flex items-center gap-2 mb-4",
        ),
        rx.cond(
            PipelineState.current_dossier_patient_summary != "",
            rx.el.div(
                rx.el.h4("Overview", class_name="text-sm font-semibold text-zinc-700 mb-1"),
                rx.el.p(
                    PipelineState.current_dossier_patient_summary,
                    class_name="text-sm text-zinc-600",
                ),
                class_name="bg-violet-50 border border-violet-100 rounded-xl p-4 mb-4",
            ),
            rx.fragment(),
        ),
        rx.foreach(
            PipelineState.current_dossier_sections,
            dossier_section_card,
        ),
        rx.cond(
            PipelineState.current_dossier_criteria.length() > 0,
            rx.el.div(
                rx.el.h4("Criterion-by-Criterion Analysis", class_name="text-sm font-semibold text-zinc-700 mb-2"),
                rx.foreach(
                    PipelineState.current_dossier_criteria,
                    dossier_criterion,
                ),
                class_name="bg-white border border-zinc-200 rounded-xl p-6 mb-4",
            ),
            rx.fragment(),
        ),
        rx.cond(
            PipelineState.current_dossier_next_steps.length() > 0,
            rx.el.div(
                rx.el.h4("Next Steps", class_name="text-sm font-semibold text-zinc-700 mb-2"),
                rx.foreach(
                    PipelineState.current_dossier_next_steps,
                    next_step_item,
                ),
                class_name="bg-white border border-zinc-200 rounded-xl p-6 mb-4",
            ),
            rx.fragment(),
        ),
        rx.cond(
            PipelineState.current_dossier_flags.length() > 0,
            rx.el.div(
                rx.el.h4(
                    rx.icon("triangle-alert", class_name="h-4 w-4 text-amber-500"),
                    "Items Needing Verification",
                    class_name="text-sm font-semibold text-zinc-700 mb-2 flex items-center gap-1.5",
                ),
                rx.foreach(
                    PipelineState.current_dossier_flags,
                    flag_item,
                ),
                class_name="bg-amber-50 border border-amber-100 rounded-xl p-4 mb-4",
            ),
            rx.fragment(),
        ),
        rx.cond(
            (pipeline["gate_id"].to(str) != "") & (pipeline["approval_status"].to(str) != "approved"),
            rx.el.div(
                rx.el.button(
                    rx.icon("check", class_name="h-4 w-4"),
                    "Proceed to Enrollment",
                    on_click=PipelineState.proceed_to_enrollment(nct_id),
                    class_name="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg px-5 py-2.5 text-sm font-medium transition-colors",
                ),
                class_name="flex justify-center mt-4",
            ),
            rx.cond(
                pipeline["approval_status"].to(str) == "approved",
                rx.el.div(
                    rx.icon("circle-check", class_name="h-4 w-4 text-emerald-500"),
                    rx.el.span("Enrollment started", class_name="text-sm text-emerald-600 font-medium"),
                    class_name="flex items-center gap-1.5 justify-center mt-4",
                ),
                rx.fragment(),
            ),
        ),
        class_name="fade-in",
    )
