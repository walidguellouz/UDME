from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token
from . import views as v
urlpatterns = [
    path("health", v.HealthView.as_view()),
    path("sites", v.SitesView.as_view()),
    path("auth/login", obtain_auth_token),
    path("auth/me", v.MeView.as_view()),
    path("scans/<uuid:pk>/tables", v.TablesView.as_view()),
    path("sites/<uuid:site_id>/enrollment-tokens", v.EnrollmentTokenView.as_view()),
    path("agents/enroll", v.AgentEnrollView.as_view()),
    path("agents/<uuid:agent_id>/revoke", v.AgentRevokeView.as_view()),
    path("scans/ingest", v.IngestView.as_view()),
    path("scans", v.ScanListView.as_view()),
    path("scans/<uuid:pk>", v.ScanDetailView.as_view()),
    path("scans/<uuid:pk>/graph", v.GraphView.as_view()),
    path("scans/<uuid:pk>/export", v.ExportView.as_view()),
    path("scans/<uuid:pk>/diff/<uuid:base_pk>", v.DiffView.as_view()),
    path("relationships/<uuid:pk>/review", v.ReviewView.as_view(kind="relationship")),
    path("mappings/<uuid:pk>/review", v.ReviewView.as_view(kind="mapping")),
]
