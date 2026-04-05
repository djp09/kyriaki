import reflex as rx

from ..states.intake_state import IntakeState


def step_dot(index: int) -> rx.Component:
    return rx.el.div(
        class_name=rx.cond(
            IntakeState.step == index,
            "w-3 h-3 rounded-full bg-violet-600",
            rx.cond(
                IntakeState.step > index,
                "w-3 h-3 rounded-full bg-violet-400",
                "w-3 h-3 rounded-full bg-zinc-300",
            ),
        ),
    )


def field_error(field_key: str) -> rx.Component:
    return rx.cond(
        IntakeState.errors.contains(field_key),
        rx.el.p(
            IntakeState.errors[field_key].to(str),
            class_name="text-xs text-red-500 mt-1",
        ),
        rx.fragment(),
    )


def select_option(val: str) -> rx.Component:
    return rx.el.option(val, value=val)


INPUT_CLASS = "w-full px-3 py-2 rounded-lg border border-zinc-300 focus:border-violet-500 focus:ring-2 focus:ring-violet-200 text-sm outline-none transition-all"
SELECT_CLASS = "w-full px-3 py-2 rounded-lg border border-zinc-300 focus:border-violet-500 focus:ring-2 focus:ring-violet-200 text-sm outline-none appearance-none bg-white transition-all"
TEXTAREA_CLASS = "w-full px-3 py-2 rounded-lg border border-zinc-300 focus:border-violet-500 focus:ring-2 focus:ring-violet-200 text-sm outline-none transition-all min-h-[100px] resize-y"


def cancer_info_step() -> rx.Component:
    return rx.el.div(
        rx.el.h3("Cancer Information", class_name="text-lg font-semibold text-zinc-800 mb-4"),
        rx.el.div(
            rx.el.label("Cancer Type", html_for="cancer_type", class_name="text-sm font-medium text-zinc-700"),
            rx.el.div(
                rx.el.select(
                    rx.el.option("Select cancer type...", value="", disabled=True),
                    rx.foreach(IntakeState.cancer_types, select_option),
                    id="cancer_type",
                    name="cancer_type",
                    value=IntakeState.cancer_type,
                    on_change=IntakeState.set_cancer_type,
                    class_name=SELECT_CLASS,
                ),
                rx.icon("chevron-down", class_name="h-4 w-4 text-zinc-400 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none"),
                class_name="relative",
            ),
            field_error("cancer_type"),
            class_name="flex flex-col gap-1 mb-4",
        ),
        rx.el.div(
            rx.el.label("Stage", html_for="cancer_stage", class_name="text-sm font-medium text-zinc-700"),
            rx.el.div(
                rx.el.select(
                    rx.el.option("Select stage...", value="", disabled=True),
                    rx.foreach(IntakeState.stages, select_option),
                    id="cancer_stage",
                    name="cancer_stage",
                    value=IntakeState.cancer_stage,
                    on_change=IntakeState.set_cancer_stage,
                    class_name=SELECT_CLASS,
                ),
                rx.icon("chevron-down", class_name="h-4 w-4 text-zinc-400 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none"),
                class_name="relative",
            ),
            field_error("cancer_stage"),
            class_name="flex flex-col gap-1 mb-4",
        ),
        rx.el.div(
            rx.el.label("Biomarkers", html_for="biomarkers", class_name="text-sm font-medium text-zinc-700"),
            rx.el.input(
                id="biomarkers",
                name="biomarkers",
                placeholder="e.g. EGFR+, PD-L1 80%, ALK- (comma-separated)",
                default_value=IntakeState.biomarkers,
                on_change=IntakeState.set_biomarkers.debounce(500),
                auto_complete="on",
                class_name=INPUT_CLASS,
            ),
            class_name="flex flex-col gap-1",
        ),
        class_name="slide-in-right",
    )


def treatment_history_step() -> rx.Component:
    return rx.el.div(
        rx.el.h3("Treatment History", class_name="text-lg font-semibold text-zinc-800 mb-4"),
        rx.el.div(
            rx.el.label("Prior Treatments", html_for="prior_treatments", class_name="text-sm font-medium text-zinc-700"),
            rx.el.textarea(
                id="prior_treatments",
                name="prior_treatments",
                placeholder="List prior treatments, one per line or comma-separated",
                default_value=IntakeState.prior_treatments,
                on_change=IntakeState.set_prior_treatments.debounce(500),
                class_name=TEXTAREA_CLASS,
            ),
            class_name="flex flex-col gap-1 mb-4",
        ),
        rx.el.div(
            rx.el.label("Lines of Therapy", html_for="lines_of_therapy", class_name="text-sm font-medium text-zinc-700"),
            rx.el.div(
                rx.el.select(
                    rx.foreach(IntakeState.lines_options, select_option),
                    id="lines_of_therapy",
                    name="lines_of_therapy",
                    value=IntakeState.lines_of_therapy.to_string(),
                    on_change=IntakeState.set_lines_of_therapy,
                    class_name=SELECT_CLASS,
                ),
                rx.icon("chevron-down", class_name="h-4 w-4 text-zinc-400 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none"),
                class_name="relative",
            ),
            class_name="flex flex-col gap-1",
        ),
        class_name="slide-in-right",
    )


def demographics_step() -> rx.Component:
    return rx.el.div(
        rx.el.h3("About You", class_name="text-lg font-semibold text-zinc-800 mb-4"),
        rx.el.div(
            rx.el.label("Age", html_for="age", class_name="text-sm font-medium text-zinc-700"),
            rx.el.input(
                id="age",
                name="age",
                type="number",
                placeholder="e.g. 55",
                default_value=IntakeState.age,
                on_change=IntakeState.set_age.debounce(500),
                auto_complete="on",
                class_name=INPUT_CLASS,
            ),
            field_error("age"),
            class_name="flex flex-col gap-1 mb-4",
        ),
        rx.el.div(
            rx.el.label("Sex", html_for="sex", class_name="text-sm font-medium text-zinc-700"),
            rx.el.div(
                rx.el.select(
                    rx.el.option("Select...", value=""),
                    rx.el.option("Male", value="male"),
                    rx.el.option("Female", value="female"),
                    id="sex",
                    name="sex",
                    value=IntakeState.sex,
                    on_change=IntakeState.set_sex,
                    class_name=SELECT_CLASS,
                ),
                rx.icon("chevron-down", class_name="h-4 w-4 text-zinc-400 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none"),
                class_name="relative",
            ),
            field_error("sex"),
            class_name="flex flex-col gap-1 mb-4",
        ),
        rx.el.div(
            rx.el.label("ECOG Performance Status", html_for="ecog_score", class_name="text-sm font-medium text-zinc-700"),
            rx.el.div(
                rx.el.select(
                    rx.el.option("Not specified", value=""),
                    rx.el.option("0 - Fully active", value="0"),
                    rx.el.option("1 - Restricted but ambulatory", value="1"),
                    rx.el.option("2 - Ambulatory, self-care capable", value="2"),
                    rx.el.option("3 - Limited self-care", value="3"),
                    rx.el.option("4 - Completely disabled", value="4"),
                    id="ecog_score",
                    name="ecog_score",
                    value=IntakeState.ecog_score,
                    on_change=IntakeState.set_ecog_score,
                    class_name=SELECT_CLASS,
                ),
                rx.icon("chevron-down", class_name="h-4 w-4 text-zinc-400 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none"),
                class_name="relative",
            ),
            class_name="flex flex-col gap-1 mb-4",
        ),
        rx.el.div(
            rx.el.label("Additional Conditions", html_for="additional_conditions", class_name="text-sm font-medium text-zinc-700"),
            rx.el.input(
                id="additional_conditions",
                name="additional_conditions",
                placeholder="e.g. diabetes, hypertension (comma-separated)",
                default_value=IntakeState.additional_conditions,
                on_change=IntakeState.set_additional_conditions.debounce(500),
                auto_complete="on",
                class_name=INPUT_CLASS,
            ),
            class_name="flex flex-col gap-1",
        ),
        class_name="slide-in-right",
    )


def labs_step() -> rx.Component:
    return rx.el.div(
        rx.el.h3("Lab Values", class_name="text-lg font-semibold text-zinc-800 mb-1"),
        rx.el.p("Optional — helps improve match accuracy.", class_name="text-sm text-zinc-500 mb-4"),
        rx.el.div(
            rx.el.div(
                rx.el.label("WBC (10^3/uL)", html_for="key_labs_wbc", class_name="text-sm font-medium text-zinc-700"),
                rx.el.input(
                    id="key_labs_wbc",
                    name="key_labs_wbc",
                    type="number",
                    step="0.1",
                    placeholder="e.g. 5.2",
                    default_value=IntakeState.key_labs_wbc,
                    on_change=IntakeState.set_key_labs_wbc.debounce(500),
                    class_name=INPUT_CLASS,
                ),
                field_error("key_labs_wbc"),
                class_name="flex flex-col gap-1",
            ),
            rx.el.div(
                rx.el.label("Platelets (10^3/uL)", html_for="key_labs_platelets", class_name="text-sm font-medium text-zinc-700"),
                rx.el.input(
                    id="key_labs_platelets",
                    name="key_labs_platelets",
                    type="number",
                    step="1",
                    placeholder="e.g. 180",
                    default_value=IntakeState.key_labs_platelets,
                    on_change=IntakeState.set_key_labs_platelets.debounce(500),
                    class_name=INPUT_CLASS,
                ),
                field_error("key_labs_platelets"),
                class_name="flex flex-col gap-1",
            ),
            rx.el.div(
                rx.el.label("Hemoglobin (g/dL)", html_for="key_labs_hemoglobin", class_name="text-sm font-medium text-zinc-700"),
                rx.el.input(
                    id="key_labs_hemoglobin",
                    name="key_labs_hemoglobin",
                    type="number",
                    step="0.1",
                    placeholder="e.g. 13.5",
                    default_value=IntakeState.key_labs_hemoglobin,
                    on_change=IntakeState.set_key_labs_hemoglobin.debounce(500),
                    class_name=INPUT_CLASS,
                ),
                field_error("key_labs_hemoglobin"),
                class_name="flex flex-col gap-1",
            ),
            rx.el.div(
                rx.el.label("Creatinine (mg/dL)", html_for="key_labs_creatinine", class_name="text-sm font-medium text-zinc-700"),
                rx.el.input(
                    id="key_labs_creatinine",
                    name="key_labs_creatinine",
                    type="number",
                    step="0.1",
                    placeholder="e.g. 0.9",
                    default_value=IntakeState.key_labs_creatinine,
                    on_change=IntakeState.set_key_labs_creatinine.debounce(500),
                    class_name=INPUT_CLASS,
                ),
                field_error("key_labs_creatinine"),
                class_name="flex flex-col gap-1",
            ),
            class_name="grid grid-cols-2 gap-4",
        ),
        class_name="slide-in-right",
    )


def location_step() -> rx.Component:
    return rx.el.div(
        rx.el.h3("Location & Preferences", class_name="text-lg font-semibold text-zinc-800 mb-4"),
        rx.el.div(
            rx.el.label("ZIP Code", html_for="location_zip", class_name="text-sm font-medium text-zinc-700"),
            rx.el.input(
                id="location_zip",
                name="postal-code",
                placeholder="e.g. 10001",
                default_value=IntakeState.location_zip,
                on_change=IntakeState.set_location_zip.debounce(500),
                auto_complete="postal-code",
                class_name=INPUT_CLASS,
            ),
            field_error("location_zip"),
            class_name="flex flex-col gap-1 mb-4",
        ),
        rx.el.div(
            rx.el.label("Willing to Travel (miles)", html_for="travel_miles", class_name="text-sm font-medium text-zinc-700"),
            rx.el.input(
                id="travel_miles",
                name="travel_miles",
                type="number",
                placeholder="50",
                default_value=IntakeState.willing_to_travel_miles.to_string(),
                on_change=IntakeState.set_willing_to_travel.debounce(500),
                class_name=INPUT_CLASS,
            ),
            class_name="flex flex-col gap-1 mb-4",
        ),
        rx.el.div(
            rx.el.label("Additional Notes", html_for="additional_notes", class_name="text-sm font-medium text-zinc-700"),
            rx.el.textarea(
                id="additional_notes",
                name="additional_notes",
                placeholder="Anything else you'd like us to know...",
                default_value=IntakeState.additional_notes,
                on_change=IntakeState.set_additional_notes.debounce(500),
                class_name="w-full px-3 py-2 rounded-lg border border-zinc-300 focus:border-violet-500 focus:ring-2 focus:ring-violet-200 text-sm outline-none transition-all min-h-[80px] resize-y",
            ),
            class_name="flex flex-col gap-1",
        ),
        class_name="slide-in-right",
    )


def intake_form() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.h2(
                "Tell us about yourself",
                class_name="text-xl font-semibold text-zinc-800 font-['Outfit'] text-center",
            ),
            rx.el.p(
                "We'll use this to find the best clinical trial matches for you.",
                class_name="text-sm text-zinc-500 mt-1 text-center",
            ),
            class_name="mb-6",
        ),
        rx.el.nav(
            rx.foreach(IntakeState.step_indices, step_dot),
            class_name="flex items-center justify-center gap-2 mb-6",
        ),
        rx.el.div(
            rx.match(
                IntakeState.step,
                (0, cancer_info_step()),
                (1, treatment_history_step()),
                (2, demographics_step()),
                (3, labs_step()),
                (4, location_step()),
                rx.el.div(),
            ),
            class_name="bg-white border border-zinc-200 rounded-xl p-6",
        ),
        rx.el.div(
            rx.cond(
                IntakeState.step > 0,
                rx.el.button(
                    rx.icon("arrow-left", class_name="h-4 w-4"),
                    "Back",
                    on_click=IntakeState.prev_step,
                    class_name="flex items-center gap-1.5 text-sm font-medium text-zinc-600 border border-zinc-300 rounded-lg px-4 py-2 hover:bg-zinc-50 transition-colors",
                ),
                rx.el.div(),
            ),
            rx.cond(
                IntakeState.step < 4,
                rx.el.button(
                    "Continue",
                    rx.icon("arrow-right", class_name="h-4 w-4"),
                    on_click=IntakeState.next_step,
                    class_name="flex items-center gap-1.5 text-sm font-medium bg-violet-600 hover:bg-violet-700 text-white rounded-lg px-5 py-2 transition-colors ml-auto",
                ),
                rx.el.button(
                    rx.icon("search", class_name="h-4 w-4"),
                    "Find my matches",
                    on_click=IntakeState.submit_form,
                    class_name="flex items-center gap-1.5 text-sm font-medium bg-violet-600 hover:bg-violet-700 text-white rounded-lg px-5 py-2 transition-colors ml-auto",
                ),
            ),
            class_name="flex items-center justify-between mt-4",
        ),
        class_name="max-w-lg mx-auto fade-in",
    )
