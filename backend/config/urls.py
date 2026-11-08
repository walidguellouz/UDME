from django.urls import path, re_path, include
from udme_api.views import spa
urlpatterns = [path("api/v1/", include("udme_api.urls")), re_path(r"^(?!api/)(?P<path>.*)$", spa)]
