import reflex as rx

from ..states.pipeline_state import PipelineState


def contact_card(contact: dict) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.icon("user", class_name="h-4 w-4 text-violet-500 shrink-0"),
            rx.el.div(
                rx.el.p(contact.get("name", "").to(str), class_name="text-sm font-semibold text-zinc-800"),
                rx.cond(
                    contact.get("role", "").to(str) != "",
                    rx.el.p(contact["role"].to(str), class_name="text-xs text-zinc-500"),
                    rx.fragment(),
                ),
            ),
            class_name="flex items-start gap-2 mb-2",
        ),
        rx.cond(
            contact.get("facility", "").to(str) != "",
            rx.el.div(
                rx.icon("building-2", class_name="h-3.5 w-3.5 text-zinc-400 shrink-0"),
                rx.el.p(
                    contact["facility"].to(str) + " · " + contact.get("city", "").to(str) + ", " + contact.get("state", "").to(str),
                    class_name="text-xs text-zinc-600",
                ),
                class_name="flex items-center gap-1.5 mb-1",
            ),
            rx.fragment(),
        ),
        rx.cond(
            contact.get("email", "").to(str) != "",
            rx.el.div(
                rx.icon("mail", class_name="h-3.5 w-3.5 text-zinc-400 shrink-0"),
                rx.el.p(contact["email"].to(str), class_name="text-xs text-zinc-600 font-mono"),
                class_name="flex items-center gap-1.5 mb-1",
            ),
            rx.fragment(),
        ),
        rx.cond(
            contact.get("phone", "").to(str) != "",
            rx.el.div(
                rx.icon("phone", class_name="h-3.5 w-3.5 text-zinc-400 shrink-0"),
                rx.el.p(contact["phone"].to(str), class_name="text-xs text-zinc-600 font-mono"),
                class_name="flex items-center gap-1.5",
            ),
            rx.fragment(),
        ),
        class_name="bg-zinc-50 border border-zinc-200 rounded-lg p-3",
    )


def outreach_view() -> rx.Component:
    return rx.el.div(
        rx.el.button(
            rx.icon("arrow-left", class_name="h-4 w-4"),
            "Back to results",
            on_click=PipelineState.back_to_results,
            class_name="flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-700 font-medium transition-colors mb-4",
        ),
        rx.el.div(
            rx.icon("mail", class_name="h-5 w-5 text-violet-500"),
            rx.el.h2(
                "Outreach Message",
                class_name="text-xl font-semibold text-zinc-800 font-['Outfit']",
            ),
            class_name="flex items-center gap-2 mb-4",
        ),
        rx.el.div(
            rx.el.div(
                rx.icon("info", class_name="h-4 w-4 text-blue-500 shrink-0 mt-0.5"),
                rx.el.p(
                    "This message is ready for you to review and send to the trial site coordinator. Nothing has been sent yet.",
                    class_name="text-sm text-blue-700",
                ),
                class_name="flex items-start gap-2 bg-blue-50 border border-blue-100 rounded-lg p-3 mb-4",
            ),
        ),
        rx.el.div(
            rx.el.h3("Message Draft", class_name="text-base font-semibold text-zinc-800 mb-3"),
            rx.cond(
                PipelineState.current_outreach_subject != "",
                rx.el.div(
                    rx.el.p("Subject", class_name="text-xs font-medium text-zinc-500 uppercase tracking-wide"),
                    rx.el.p(
                        PipelineState.current_outreach_subject,
                        class_name="text-sm text-zinc-800 mt-0.5",
                    ),
                    class_name="py-2 border-b border-zinc-100",
                ),
                rx.fragment(),
            ),
            rx.cond(
                PipelineState.current_outreach_message != "",
                rx.el.div(
                    rx.el.p("Message", class_name="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-1"),
                    rx.el.pre(
                        PipelineState.current_outreach_message,
                        class_name="text-sm text-zinc-800 mt-0.5 whitespace-pre-wrap font-['DM_Sans']",
                    ),
                    class_name="py-2",
                ),
                rx.fragment(),
            ),
            class_name="bg-white border border-zinc-200 rounded-xl p-6 mb-4",
        ),
        rx.cond(
            PipelineState.current_outreach_contacts.length() > 0,
            rx.el.div(
                rx.el.h3("Site Contacts", class_name="text-base font-semibold text-zinc-800 mb-3"),
                rx.el.div(
                    rx.foreach(PipelineState.current_outreach_contacts, contact_card),
                    class_name="flex flex-col gap-2",
                ),
                class_name="bg-white border border-zinc-200 rounded-xl p-6 mb-4",
            ),
            rx.fragment(),
        ),
        class_name="fade-in",
    )
