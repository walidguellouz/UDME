"""Control-plane model (plan section 11). Tenant-owned rows carry tenant FK.
Packages hold metadata only — never pharmacy records."""
import uuid, hashlib, secrets
from django.conf import settings
from django.db import models
from django.utils import timezone


class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    plan = models.CharField(max_length=50, default="starter")
    created_at = models.DateTimeField(auto_now_add=True)


class Membership(models.Model):
    ROLES = [("admin", "admin"), ("reviewer", "reviewer"), ("viewer", "viewer")]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLES, default="viewer")
    class Meta: unique_together = ("tenant", "user")


class Site(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    class Meta: unique_together = ("tenant", "name")


def _h(v: str) -> str: return hashlib.sha256(v.encode()).hexdigest()


class EnrollmentToken(models.Model):
    token_hash = models.CharField(max_length=64, unique=True)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    site = models.ForeignKey(Site, on_delete=models.CASCADE)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True)

    @classmethod
    def issue(cls, site: Site, minutes: int = 30) -> str:
        raw = secrets.token_urlsafe(32)
        cls.objects.create(token_hash=_h(raw), tenant=site.tenant, site=site,
                           expires_at=timezone.now() + timezone.timedelta(minutes=minutes))
        return raw

    @classmethod
    def consume(cls, raw: str):
        t = cls.objects.select_for_update().filter(token_hash=_h(raw), used_at__isnull=True,
                                                   expires_at__gt=timezone.now()).first()
        if t: t.used_at = timezone.now(); t.save(update_fields=["used_at"])
        return t


class Agent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    site = models.ForeignKey(Site, on_delete=models.CASCADE)
    name = models.CharField(max_length=200, blank=True)
    # MVP: shared HMAC secret. TODO(hardening): replace by per-agent Ed25519 public key; keep secrets in a KMS.
    secret = models.CharField(max_length=128)
    revoked = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(null=True)


class ScanPackage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    site = models.ForeignKey(Site, on_delete=models.CASCADE)
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT)
    scan_id = models.UUIDField()  # agent-supplied idempotency key
    nonce = models.CharField(max_length=64)
    checksum = models.CharField(max_length=64)
    schema_hash = models.CharField(max_length=64, blank=True)
    engine = models.CharField(max_length=50); engine_version = models.CharField(max_length=50, blank=True)
    STATUS = [("analyzing", "analyzing"), ("review_required", "review_required"), ("failed", "failed")]
    status = models.CharField(max_length=20, choices=STATUS, default="analyzing")
    package = models.JSONField()  # immutable; move to S3-compatible storage at scale
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = [("agent", "scan_id"), ("agent", "nonce")]  # idempotency + replay protection


class RelationshipCandidate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    scan = models.ForeignKey(ScanPackage, on_delete=models.CASCADE, related_name="relationships")
    data = models.JSONField(); score = models.FloatField()
    status = models.CharField(max_length=20, default="needs_review")  # needs_review|accepted|rejected|investigate


class BusinessMapping(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    scan = models.ForeignKey(ScanPackage, on_delete=models.CASCADE, related_name="mappings")
    object_id = models.CharField(max_length=500); label = models.CharField(max_length=100)
    confidence = models.FloatField(); evidence = models.JSONField(default=list); alternatives = models.JSONField(default=list)
    status = models.CharField(max_length=20, default="needs_review")  # needs_review|approved|rejected|edited


class MappingReview(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    target_type = models.CharField(max_length=20); target_id = models.UUIDField()
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    previous = models.CharField(max_length=100); decision = models.CharField(max_length=20)
    new_label = models.CharField(max_length=100, blank=True); comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AuditEvent(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=True)
    actor = models.CharField(max_length=100); action = models.CharField(max_length=100)
    resource = models.CharField(max_length=200, blank=True); details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
