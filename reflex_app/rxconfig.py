import reflex as rx
from reflex.plugins.sitemap import SitemapPlugin
from reflex.plugins.tailwind_v4 import TailwindV4Plugin

config = rx.Config(
    app_name="kyriaki_app",
    plugins=[SitemapPlugin(), TailwindV4Plugin()],
    backend_port=8001,
    frontend_port=3000,
)
