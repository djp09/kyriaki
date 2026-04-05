import reflex as rx

from ..states.pipeline_state import PipelineState


def list_item(item: str) -> rx.Component:
    return rx.el.li(
        item,
        class_name="text-sm text-zinc-700 py-1",
    )


def check_item(item: str) -> rx.Component:
    return rx.el.div(
        rx.icon("check", class_name="h-3.5 w-3.5 text-emerald-500 shrink-0 mt-0.5"),
        rx.el.p(item, class_name="text-sm text-zinc-700"),
        class_name="flex items-start gap-2 py-1",
    )


def field_row(label: str, value: rx.Var) -> rx.Component:
    return rx.cond(
        value != "",
        rx.el.div(
            rx.el.p(label, class_name="text-xs font-medium text-zinc-500 uppercase tracking-wide"),
            rx.el.p(value, class_name="text-sm text-zinc-800 mt-0.5 whitespace-pre-wrap"),
            class_name="py-2 border-b border-zinc-100 last:border-0",
        ),
        rx.fragment(),
    )


def patient_packet_card() -> rx.Component:
    packet = PipelineState.current_patient_packet
    return rx.cond(
        packet.length() > 0,
        rx.el.div(
            rx.el.div(
                rx.icon("clipboard-list", class_name="h-5 w-5 text-violet-500"),
                rx.el.h3("Patient Screening Packet", class_name="text-base font-semibold text-zinc-800"),
                class_name="flex items-center gap-2 mb-4",
            ),
            rx.cond(
                PipelineState.current_patient_packet_checklist.length() > 0,
                rx.el.div(
                    rx.el.p("Screening Checklist", class_name="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-2"),
                    rx.foreach(PipelineState.current_patient_packet_checklist, check_item),
                    class_name="mb-4 bg-emerald-50 border border-emerald-100 rounded-lg p-4",
                ),
                rx.fragment(),
            ),
            field_row("Diagnosis Summary", packet.get("diagnosis_summary", "")),
            field_row("Treatment History", packet.get("treatment_history", "")),
            field_row("Match Rationale", packet.get("match_rationale", "")),
            field_row("Prescreening Status", packet.get("prescreening_status", "")),
            field_row("Insurance Notes", packet.get("insurance_notes", "")),
            rx.cond(
                PipelineState.current_patient_packet_considerations.length() > 0,
                rx.el.div(
                    rx.el.p("Special Considerations", class_name="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-2"),
                    rx.el.ul(
                        rx.foreach(PipelineState.current_patient_packet_considerations, list_item),
                        class_name="list-disc list-inside",
                    ),
                    class_name="py-2",
                ),
                rx.fragment(),
            ),
            class_name="bg-white border border-zinc-200 rounded-xl p-6 mb-4",
        ),
        rx.fragment(),
    )


def prep_guide_card() -> rx.Component:
    guide = PipelineState.current_prep_guide
    return rx.cond(
        guide.length() > 0,
        rx.el.div(
            rx.el.div(
                rx.icon("book-open", class_name="h-5 w-5 text-violet-500"),
                rx.el.h3("Your Prep Guide", class_name="text-base font-semibold text-zinc-800"),
                class_name="flex items-center gap-2 mb-4",
            ),
            field_row("What to Expect", guide.get("what_to_expect", "")),
            rx.cond(
                PipelineState.current_prep_documents.length() > 0,
                rx.el.div(
                    rx.el.p("Documents to Bring", class_name="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-2"),
                    rx.el.ul(
                        rx.foreach(PipelineState.current_prep_documents, list_item),
                        class_name="list-disc list-inside",
                    ),
                    class_name="py-2 border-b border-zinc-100",
                ),
                rx.fragment(),
            ),
            rx.cond(
                PipelineState.current_prep_questions.length() > 0,
                rx.el.div(
                    rx.el.p("Questions to Ask", class_name="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-2"),
                    rx.el.ul(
                        rx.foreach(PipelineState.current_prep_questions, list_item),
                        class_name="list-disc list-inside",
                    ),
                    class_name="py-2 border-b border-zinc-100",
                ),
                rx.fragment(),
            ),
            rx.cond(
                PipelineState.current_prep_steps.length() > 0,
                rx.el.div(
                    rx.el.p("How to Prepare", class_name="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-2"),
                    rx.el.ul(
                        rx.foreach(PipelineState.current_prep_steps, list_item),
                        class_name="list-disc list-inside",
                    ),
                    class_name="py-2",
                ),
                rx.fragment(),
            ),
            class_name="bg-white border border-zinc-200 rounded-xl p-6 mb-4",
        ),
        rx.fragment(),
    )


def outreach_draft_card() -> rx.Component:
    draft = PipelineState.current_outreach_draft
    return rx.cond(
        draft.length() > 0,
        rx.el.div(
            rx.el.div(
                rx.icon("mail", class_name="h-5 w-5 text-violet-500"),
                rx.el.h3("Draft Message to Site Coordinator", class_name="text-base font-semibold text-zinc-800"),
                class_name="flex items-center gap-2 mb-4",
            ),
            field_row("Subject", draft.get("subject_line", "")),
            field_row("Message", draft.get("message_body", "")),
            field_row("Follow-up Notes", draft.get("follow_up_notes", "")),
            class_name="bg-white border border-zinc-200 rounded-xl p-6 mb-4",
        ),
        rx.fragment(),
    )


def enrollment_view() -> rx.Component:
    nct_id = PipelineState.viewing_enrollment_nct_id
    pipeline = PipelineState.pipelines.get(nct_id, {
        "enrollment_gate_id": "",
        "enrollment_status": "",
    })

    return rx.el.div(
        rx.el.button(
            rx.icon("arrow-left", class_name="h-4 w-4"),
            "Back to results",
            on_click=PipelineState.back_to_results,
            class_name="flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-700 font-medium transition-colors mb-4",
        ),
        rx.el.div(
            rx.icon("package", class_name="h-5 w-5 text-violet-500"),
            rx.el.div(
                rx.el.h2(
                    "Enrollment Packet",
                    class_name="text-xl font-semibold text-zinc-800 font-['Outfit']",
                ),
                rx.cond(
                    PipelineState.current_enrollment_trial_title != "",
                    rx.el.p(
                        PipelineState.current_enrollment_trial_title,
                        class_name="text-sm text-zinc-500",
                    ),
                    rx.fragment(),
                ),
            ),
            class_name="flex items-center gap-2 mb-4",
        ),
        patient_packet_card(),
        prep_guide_card(),
        outreach_draft_card(),
        rx.cond(
            (pipeline["enrollment_gate_id"].to(str) != "") & (pipeline["enrollment_status"].to(str) == "done"),
            rx.el.div(
                rx.el.button(
                    rx.icon("send", class_name="h-4 w-4"),
                    "Approve & Send to Site",
                    on_click=PipelineState.approve_enrollment(nct_id),
                    class_name="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg px-5 py-2.5 text-sm font-medium transition-colors",
                ),
                class_name="flex justify-center mt-4",
            ),
            rx.fragment(),
        ),
        class_name="fade-in",
    )
