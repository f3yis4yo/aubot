from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, Http404
from django.urls import path, re_path
from ninja import NinjaAPI

from buddy.api import router as buddy_router
from chat.api import public_router
from chat.api import router as chat_router
from chat.staff_api import router as staff_router
from core.api import auth_router, settings_router
from documents.api import router as documents_router
from documents.api import staff_router as documents_staff_router
from evaluation.api import router as evaluation_router

api = NinjaAPI(
    title="AUBOT API",
    version="1.0.0",
    description="Customer-service assistant for Australian SMEs: UC01 enquiries, UC02 documents, UC03 escalation, Buddy voice.",
    docs_url="/docs",
)
api.add_router("/", public_router)
api.add_router("/auth", auth_router)
api.add_router("/chat", chat_router)
api.add_router("/chat", documents_router)
api.add_router("/chat", buddy_router)
api.add_router("/staff", staff_router)
api.add_router("/staff", documents_staff_router)
api.add_router("/staff", settings_router)
api.add_router("/staff", evaluation_router)


def spa(request, *args, **kwargs):
    """Serve the built React app for any non-API route (client-side routing)."""
    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        raise Http404("Frontend not built. Run `npm run build` in frontend/, or use the Vite dev server on :5173.")
    return FileResponse(index.open("rb"), content_type="text/html")


admin.site.site_header = "AUBOT administration"
admin.site.site_title = "AUBOT admin"

urlpatterns = [
    path("api/", api.urls),
    path("admin/", admin.site.urls),
    re_path(r"^(?!api/|admin/|static/|ws/).*$", spa),
]
