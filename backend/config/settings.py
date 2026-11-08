import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")
if not DEBUG and SECRET_KEY == "dev-only-change-me":
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG=0")
RENDER_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME")  # injected automatically by Render
ALLOWED_HOSTS = ([RENDER_HOST] if RENDER_HOST else []) + [h for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1" if not DEBUG else "*").split(",") if h]
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h not in ("*", "localhost", "127.0.0.1")]
INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions",
                  "django.contrib.messages", "rest_framework", "rest_framework.authtoken", "udme_api"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "whitenoise.middleware.WhiteNoiseMiddleware", "django.contrib.sessions.middleware.SessionMiddleware",
              "django.middleware.common.CommonMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware"]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True,
              "OPTIONS": {"context_processors": ["django.template.context_processors.request",
                                                 "django.contrib.auth.context_processors.auth",
                                                 "django.contrib.messages.context_processors.messages"]}}]
# PostgreSQL in real deployments (DATABASE_URL-style env); sqlite fallback for dev/tests.
import dj_database_url
if os.environ.get("DATABASE_URL"):  # Render: wired from the managed Postgres
    DATABASES = {"default": dj_database_url.config(conn_max_age=600)}
elif os.environ.get("POSTGRES_DB"):
    DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": os.environ["POSTGRES_DB"],
                 "USER": os.environ.get("POSTGRES_USER", "udme"), "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
                 "HOST": os.environ.get("POSTGRES_HOST", "db"), "PORT": "5432"}}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication",
                                       "rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle", "rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": "600/hour", "anon": "120/hour"},  # slows brute force on login/enroll
}
# Celery (Redis). Eager mode runs tasks inline when no broker is configured.
CELERY_BROKER_URL = os.environ.get("REDIS_URL", "memory://")
CELERY_TASK_ALWAYS_EAGER = not os.environ.get("REDIS_URL")
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024
STATIC_URL = "/static/"; STATIC_ROOT = BASE_DIR / "staticfiles"
WHITENOISE_ROOT = BASE_DIR / "frontend_dist"   # Angular build, served at the site root
WHITENOISE_INDEX_FILE = True
FRONTEND_INDEX = BASE_DIR / "frontend_dist" / "index.html"
if not DEBUG:
    SECURE_SSL_REDIRECT = True; SECURE_REDIRECT_EXEMPT = [r"^api/v1/health$"]
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000; SECURE_CONTENT_TYPE_NOSNIFF = True
