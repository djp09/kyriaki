import reflex as rx

from .states.navigation_state import NavigationState
from .states.upload_state import UploadState
from .states.intake_state import IntakeState
from .states.match_state import MatchState
from .states.pipeline_state import PipelineState
from .components.layout import header, error_banner, agent_badge
from .components.document_upload import document_upload
from .components.intake_form import intake_form
from .components.loading_view import loading_view
from .components.trial_results import trial_results
from .components.trial_detail import trial_detail
from .components.dossier_view import dossier_view
from .components.enrollment_view import enrollment_view
from .components.outreach_view import outreach_view


def index() -> rx.Component:
    return rx.el.main(
        header(),
        error_banner(),
        agent_badge(),
        rx.el.div(
            rx.match(
                NavigationState.view,
                ("upload", document_upload()),
                ("intake", intake_form()),
                ("loading", loading_view()),
                ("results", trial_results()),
                ("detail", trial_detail()),
                ("dossier", dossier_view()),
                ("enrollment", enrollment_view()),
                ("outreach", outreach_view()),
                rx.el.div(),
            ),
            class_name="max-w-3xl mx-auto px-4 py-8",
        ),
        class_name="min-h-screen bg-zinc-100 font-['DM_Sans']",
    )


app = rx.App(
    head_components=[
        rx.el.link(
            rel="preconnect",
            href="https://fonts.googleapis.com",
        ),
        rx.el.link(
            rel="preconnect",
            href="https://fonts.gstatic.com",
            cross_origin="",
        ),
        rx.el.link(
            href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&family=DM+Sans:wght@400;500;600&display=swap",
            rel="stylesheet",
        ),
    ],
    stylesheets=["/kyriaki.css"],
    theme=rx.theme(appearance="light", has_background=False, accent_color="violet"),
)
app.add_page(index, route="/", title="Kyriaki — Clinical Trial Matching")
