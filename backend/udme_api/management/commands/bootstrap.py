"""Idempotent first-run setup from env: UDME_ADMIN_USER, UDME_ADMIN_PASSWORD, UDME_TENANT_NAME, UDME_SITE_NAME.
Skips silently if no password is provided. The password is never printed."""
import os
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from udme_api import models as M


class Command(BaseCommand):
    def handle(self, *a, **k):
        user, pw = os.environ.get("UDME_ADMIN_USER", "admin"), os.environ.get("UDME_ADMIN_PASSWORD")
        if not pw: self.stdout.write("bootstrap: UDME_ADMIN_PASSWORD not set, skipped"); return
        u, created = User.objects.get_or_create(username=user)
        if created: u.set_password(pw); u.save()   # never overwrite an existing password
        t, _ = M.Tenant.objects.get_or_create(name=os.environ.get("UDME_TENANT_NAME", "Ma pharmacie"))
        M.Membership.objects.get_or_create(tenant=t, user=u, defaults={"role": "admin"})
        M.Site.objects.get_or_create(tenant=t, name=os.environ.get("UDME_SITE_NAME", "Site principal"))
        self.stdout.write(f"bootstrap: ok (user={user}, created={created})")
