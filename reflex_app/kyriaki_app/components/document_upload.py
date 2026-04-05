import reflex as rx

from ..states.upload_state import UploadState


def extraction_result_row(item: list) -> rx.Component:
    return rx.el.div(
        rx.el.span(item[0], class_name="text-sm font-medium text-zinc-500 capitalize"),
        rx.el.span(item[1], class_name="text-sm text-zinc-800"),
        class_name="flex justify-between items-center py-1.5 border-b border-zinc-100 last:border-0",
    )


def upload_zone() -> rx.Component:
    return rx.upload(
        rx.el.div(
            rx.icon("upload", class_name="h-10 w-10 text-zinc-400 mx-auto"),
            rx.el.p(
                "Drop your medical document here",
                class_name="text-base font-medium text-zinc-700 mt-3",
            ),
            rx.el.p(
                "PDF, PNG, JPG up to 10MB",
                class_name="text-sm text-zinc-400 mt-1",
            ),
            rx.el.button(
                "Browse files",
                class_name="mt-4 text-sm font-medium text-violet-600 border border-violet-300 rounded-lg px-4 py-2 hover:bg-violet-50 transition-colors cursor-pointer",
            ),
            class_name="border-2 border-dashed border-zinc-300 rounded-xl p-12 text-center hover:border-violet-400 transition-colors cursor-pointer",
        ),
        id="doc_upload",
        accept={
            "application/pdf": [".pdf"],
            "image/png": [".png"],
            "image/jpeg": [".jpg", ".jpeg"],
            "image/gif": [".gif"],
            "image/webp": [".webp"],
        },
        max_size=10 * 1024 * 1024,
        on_drop=UploadState.handle_upload(rx.upload_files(upload_id="doc_upload")),
    )


def extraction_preview() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.icon("file-check", class_name="h-5 w-5 text-emerald-600"),
            rx.el.div(
                rx.el.p(UploadState.doc_type_label, class_name="text-sm font-semibold text-zinc-800"),
                rx.el.p(
                    UploadState.file_name,
                    class_name="text-xs text-zinc-500",
                ),
            ),
            rx.el.div(
                rx.el.span(
                    UploadState.confidence_pct.to_string() + "% confidence",
                    class_name=rx.cond(
                        UploadState.confidence >= 0.5,
                        "text-xs font-medium text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded-full",
                        "text-xs font-medium text-amber-700 bg-amber-100 px-2 py-0.5 rounded-full",
                    ),
                ),
            ),
            class_name="flex items-center gap-3 mb-4",
        ),
        rx.cond(
            UploadState.extraction_notes != "",
            rx.el.p(UploadState.extraction_notes, class_name="text-sm text-zinc-600 mb-3 italic"),
            rx.fragment(),
        ),
        rx.el.div(
            rx.el.p(
                "Extracted " + UploadState.extracted_fields_count.to_string() + " fields",
                class_name="text-sm font-medium text-zinc-600 mb-2",
            ),
            rx.foreach(
                UploadState.extracted.entries(),
                extraction_result_row,
            ),
            class_name="bg-zinc-50 rounded-lg p-4 mb-4",
        ),
        rx.el.div(
            rx.el.button(
                rx.icon("arrow-right", class_name="h-4 w-4"),
                "Use these results",
                on_click=UploadState.show_confirm,
                class_name="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors",
            ),
            rx.el.button(
                "Fill form manually instead",
                on_click=UploadState.prefill_and_go_intake,
                class_name="text-sm text-zinc-500 hover:text-zinc-700 font-medium transition-colors",
            ),
            class_name="flex items-center gap-4",
        ),
        class_name="bg-white border border-zinc-200 rounded-xl p-6 fade-in",
    )


def confirm_form() -> rx.Component:
    return rx.el.div(
        rx.el.h3("Complete required fields", class_name="text-lg font-semibold text-zinc-800 mb-1"),
        rx.el.p(
            "We need a few more details before matching.",
            class_name="text-sm text-zinc-500 mb-4",
        ),
        rx.cond(
            UploadState.upload_error != "",
            rx.el.p(UploadState.upload_error, class_name="text-sm text-red-600 mb-3"),
            rx.fragment(),
        ),
        rx.el.div(
            rx.el.label("Age", html_for="confirm_age", class_name="text-sm font-medium text-zinc-700"),
            rx.el.input(
                id="confirm_age",
                name="age",
                type="number",
                placeholder="e.g. 55",
                default_value=UploadState.confirm_age,
                on_change=UploadState.set_confirm_age.debounce(500),
                auto_complete="on",
                class_name="w-full px-3 py-2 rounded-lg border border-zinc-300 focus:border-violet-500 focus:ring-2 focus:ring-violet-200 text-sm outline-none transition-all",
            ),
            class_name="flex flex-col gap-1 mb-3",
        ),
        rx.el.div(
            rx.el.label("Sex", class_name="text-sm font-medium text-zinc-700"),
            rx.el.div(
                rx.el.select(
                    rx.el.option("Select...", value=""),
                    rx.el.option("Male", value="male"),
                    rx.el.option("Female", value="female"),
                    value=UploadState.confirm_sex,
                    on_change=UploadState.set_confirm_sex,
                    class_name="w-full px-3 py-2 rounded-lg border border-zinc-300 focus:border-violet-500 focus:ring-2 focus:ring-violet-200 text-sm outline-none appearance-none bg-white transition-all",
                ),
                rx.icon("chevron-down", class_name="h-4 w-4 text-zinc-400 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none"),
                class_name="relative",
            ),
            class_name="flex flex-col gap-1 mb-3",
        ),
        rx.el.div(
            rx.el.label("ZIP Code", html_for="confirm_zip", class_name="text-sm font-medium text-zinc-700"),
            rx.el.input(
                id="confirm_zip",
                name="postal-code",
                placeholder="e.g. 10001",
                default_value=UploadState.confirm_zip,
                on_change=UploadState.set_confirm_zip.debounce(500),
                auto_complete="postal-code",
                class_name="w-full px-3 py-2 rounded-lg border border-zinc-300 focus:border-violet-500 focus:ring-2 focus:ring-violet-200 text-sm outline-none transition-all",
            ),
            class_name="flex flex-col gap-1 mb-3",
        ),
        rx.el.div(
            rx.el.label("Willing to travel (miles)", html_for="confirm_travel", class_name="text-sm font-medium text-zinc-700"),
            rx.el.input(
                id="confirm_travel",
                name="travel_miles",
                type="number",
                placeholder="50",
                default_value=UploadState.confirm_travel,
                on_change=UploadState.set_confirm_travel.debounce(500),
                class_name="w-full px-3 py-2 rounded-lg border border-zinc-300 focus:border-violet-500 focus:ring-2 focus:ring-violet-200 text-sm outline-none transition-all",
            ),
            class_name="flex flex-col gap-1 mb-4",
        ),
        rx.el.div(
            rx.el.button(
                rx.icon("search", class_name="h-4 w-4"),
                "Find my matches",
                on_click=UploadState.confirm_submit,
                class_name="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 text-white rounded-lg px-5 py-2.5 text-sm font-medium transition-colors",
            ),
            rx.el.button(
                "Back",
                on_click=UploadState.clear_upload,
                class_name="text-sm text-zinc-500 hover:text-zinc-700 font-medium transition-colors",
            ),
            class_name="flex items-center gap-4",
        ),
        class_name="bg-white border border-zinc-200 rounded-xl p-6 fade-in",
    )


def document_upload() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.h2(
                "Get started",
                class_name="text-xl font-semibold text-zinc-800 font-['Outfit']",
            ),
            rx.el.p(
                "Upload a medical document for automatic extraction, or fill in the form manually.",
                class_name="text-sm text-zinc-500 mt-1",
            ),
            class_name="text-center mb-6",
        ),
        rx.cond(
            UploadState.upload_error != "",
            rx.el.div(
                rx.icon("circle-x", class_name="h-4 w-4 text-red-500 shrink-0"),
                rx.el.p(UploadState.upload_error, class_name="text-sm text-red-600"),
                rx.el.button(
                    "Try again",
                    on_click=UploadState.clear_upload,
                    class_name="text-xs text-red-500 hover:text-red-700 font-medium ml-auto",
                ),
                class_name="flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg p-3 mb-4 fade-in",
            ),
            rx.fragment(),
        ),
        rx.cond(
            UploadState.uploading,
            rx.el.div(
                rx.el.div(class_name="animate-pulse bg-zinc-200 h-32 rounded-xl"),
                rx.el.div(
                    rx.el.p(
                        "Extracting data from ",
                        class_name="text-sm text-zinc-500",
                    ),
                    rx.el.p(
                        UploadState.file_name,
                        class_name="text-sm font-medium text-zinc-700",
                    ),
                    class_name="flex items-center gap-1 justify-center mt-3",
                ),
                class_name="fade-in",
            ),
            rx.cond(
                UploadState.confirm_step,
                confirm_form(),
                rx.cond(
                    UploadState.has_result,
                    extraction_preview(),
                    upload_zone(),
                ),
            ),
        ),
        rx.cond(
            ~UploadState.uploading & ~UploadState.confirm_step & ~UploadState.has_result,
            rx.el.div(
                rx.el.div(
                    rx.el.div(class_name="flex-1 h-px bg-zinc-200"),
                    rx.el.span("or", class_name="text-sm text-zinc-400 px-3"),
                    rx.el.div(class_name="flex-1 h-px bg-zinc-200"),
                    class_name="flex items-center my-6",
                ),
                rx.el.button(
                    "Fill in the form manually",
                    on_click=UploadState.skip_to_intake,
                    class_name="w-full text-sm font-medium text-zinc-600 border border-zinc-300 rounded-lg px-4 py-2.5 hover:bg-zinc-50 transition-colors",
                ),
            ),
            rx.fragment(),
        ),
        class_name="max-w-lg mx-auto fade-in",
    )
