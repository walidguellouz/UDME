# Image unique : frontend Angular compilé + backend Django (gunicorn). Contexte de build = racine du dépôt.
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx ng build --configuration production

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY core /core
RUN pip install --no-cache-dir /core
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend /app
COPY --from=web /web/dist/udme/browser /app/frontend_dist
RUN mkdir -p staticfiles && useradd -m udme && chown -R udme /app
USER udme
EXPOSE 10000
# migrate + création idempotente du compte admin (si UDME_ADMIN_PASSWORD est défini), puis serveur
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py bootstrap && exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-10000} --workers 2 --timeout 120 --access-logfile -"]
