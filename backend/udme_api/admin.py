from django.contrib import admin
from . import models
for m in (models.Tenant, models.Site, models.Agent, models.ScanPackage, models.AuditEvent): admin.site.register(m)
