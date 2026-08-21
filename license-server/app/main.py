from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

PRODUCT = "dentora"
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_database_url(value: str) -> str:
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value


DATABASE_URL = normalize_database_url(os.environ["DATABASE_URL"])
ADMIN_API_KEY = os.environ["LICENSE_ADMIN_API_KEY"]
PRIVATE_KEY_B64 = os.environ["LICENSE_SIGNING_PRIVATE_KEY_B64"]
REFRESH_HOURS = int(os.getenv("LICENSE_REFRESH_HOURS", "24"))
OFFLINE_GRACE_DAYS = int(os.getenv("LICENSE_OFFLINE_GRACE_DAYS", "7"))


class Base(DeclarativeBase):
    pass


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    customer_name: Mapped[str] = mapped_column(String(200))
    plan: Mapped[str] = mapped_column(String(50), default="standard")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_activations: Mapped[int] = mapped_column(Integer, default=1)
    features: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Activation(Base):
    __tablename__ = "activations"
    __table_args__ = (
        UniqueConstraint("license_id", "installation_id", name="uq_license_installation"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    license_id: Mapped[UUID] = mapped_column(ForeignKey("licenses.id", ondelete="CASCADE"), index=True)
    installation_id: Mapped[str] = mapped_column(String(64), index=True)
    fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


def _load_private_key() -> Ed25519PrivateKey:
    try:
        pem = base64.b64decode(PRIVATE_KEY_B64)
        key = serialization.load_pem_private_key(pem, password=None)
    except Exception as exc:  # pragma: no cover - startup configuration failure
        raise RuntimeError("Invalid LICENSE_SIGNING_PRIVATE_KEY_B64") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise RuntimeError("License signing key must be Ed25519")
    return key


PRIVATE_KEY = _load_private_key()
PUBLIC_KEY: Ed25519PublicKey = PRIVATE_KEY.public_key()


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sign_payload(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = PRIVATE_KEY.sign(raw)
    return f"{b64url_encode(raw)}.{b64url_encode(signature)}"


def verify_token(token: str) -> dict:
    try:
        payload_part, signature_part = token.split(".", 1)
        raw = b64url_decode(payload_part)
        signature = b64url_decode(signature_part)
        PUBLIC_KEY.verify(signature, raw)
        payload = json.loads(raw)
    except (ValueError, InvalidSignature, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid license lease") from exc
    if payload.get("product") != PRODUCT or payload.get("v") != 1:
        raise HTTPException(status_code=401, detail="Invalid license lease")
    return payload


def hash_license_key(value: str) -> str:
    normalized = value.strip().upper().replace(" ", "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def generate_license_key() -> str:
    groups = ["".join(secrets.choice(ALPHABET) for _ in range(5)) for _ in range(5)]
    return "DP-" + "-".join(groups)


def issue_lease(license: License, activation: Activation) -> tuple[str, datetime, datetime]:
    now = utcnow()
    valid_until = now + timedelta(days=OFFLINE_GRACE_DAYS)
    if license.expires_at and license.expires_at < valid_until:
        valid_until = license.expires_at
    refresh_after = min(now + timedelta(hours=REFRESH_HOURS), valid_until)
    payload = {
        "v": 1,
        "product": PRODUCT,
        "license_id": str(license.id),
        "activation_id": str(activation.id),
        "installation_id": activation.installation_id,
        "fingerprint": activation.fingerprint,
        "customer_name": license.customer_name,
        "plan": license.plan,
        "features": license.features or [],
        "issued_at": now.isoformat(),
        "refresh_after": refresh_after.isoformat(),
        "valid_until": valid_until.isoformat(),
        "license_expires_at": license.expires_at.isoformat() if license.expires_at else None,
    }
    return sign_payload(payload), refresh_after, valid_until


def ensure_license_usable(license: License) -> None:
    now = utcnow()
    if license.status != "active":
        raise HTTPException(status_code=403, detail=f"License is {license.status}")
    if license.expires_at and license.expires_at <= now:
        raise HTTPException(status_code=403, detail="License has expired")


async def get_db():
    async with SessionLocal() as session:
        yield session


async def require_admin(x_admin_key: Annotated[str | None, Header()] = None) -> None:
    if not x_admin_key or not secrets.compare_digest(x_admin_key, ADMIN_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid admin key")


class ActivateRequest(BaseModel):
    license_key: str = Field(min_length=8, max_length=100)
    installation_id: str = Field(min_length=8, max_length=64)
    fingerprint: str = Field(min_length=16, max_length=128)
    app_version: str | None = Field(default=None, max_length=50)


class RefreshRequest(BaseModel):
    lease_token: str
    installation_id: str = Field(min_length=8, max_length=64)
    fingerprint: str = Field(min_length=16, max_length=128)


class LeaseResponse(BaseModel):
    lease_token: str
    customer_name: str
    plan: str
    features: list[str]
    refresh_after: datetime
    valid_until: datetime
    license_expires_at: datetime | None


class CreateLicenseRequest(BaseModel):
    customer_name: str = Field(min_length=1, max_length=200)
    plan: str = Field(default="standard", min_length=1, max_length=50)
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    max_activations: int = Field(default=1, ge=1, le=100)
    features: list[str] = Field(default_factory=list)


class LicenseAdminResponse(BaseModel):
    id: UUID
    customer_name: str
    plan: str
    status: str
    expires_at: datetime | None
    max_activations: int
    features: list[str]
    key_prefix: str
    active_activations: int = 0


class CreateLicenseResponse(LicenseAdminResponse):
    license_key: str


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="Dentora License Server",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy", "service": "dentora-license"}


@app.get("/v1/public-key")
async def public_key() -> dict:
    pem = PUBLIC_KEY.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return {"algorithm": "Ed25519", "public_key_pem": pem}


@app.post("/v1/activate", response_model=LeaseResponse)
async def activate(data: ActivateRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    key_hash = hash_license_key(data.license_key)
    result = await db.execute(select(License).where(License.key_hash == key_hash))
    license = result.scalar_one_or_none()
    if not license:
        raise HTTPException(status_code=404, detail="License key not found")
    ensure_license_usable(license)

    existing_result = await db.execute(
        select(Activation).where(
            Activation.license_id == license.id,
            Activation.installation_id == data.installation_id,
        )
    )
    activation = existing_result.scalar_one_or_none()

    if activation:
        if activation.revoked_at:
            raise HTTPException(status_code=403, detail="Activation has been revoked")
        if activation.fingerprint != data.fingerprint:
            raise HTTPException(status_code=409, detail="Installation fingerprint mismatch")
        activation.last_seen_at = utcnow()
    else:
        active_count = await db.scalar(
            select(func.count()).select_from(Activation).where(
                Activation.license_id == license.id,
                Activation.revoked_at.is_(None),
            )
        )
        if int(active_count or 0) >= license.max_activations:
            raise HTTPException(status_code=409, detail="License activation limit reached")
        activation = Activation(
            license_id=license.id,
            installation_id=data.installation_id,
            fingerprint=data.fingerprint,
        )
        db.add(activation)
        await db.flush()

    token, refresh_after, valid_until = issue_lease(license, activation)
    await db.commit()
    return LeaseResponse(
        lease_token=token,
        customer_name=license.customer_name,
        plan=license.plan,
        features=license.features or [],
        refresh_after=refresh_after,
        valid_until=valid_until,
        license_expires_at=license.expires_at,
    )


@app.post("/v1/refresh", response_model=LeaseResponse)
async def refresh(data: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    payload = verify_token(data.lease_token)
    if payload.get("installation_id") != data.installation_id:
        raise HTTPException(status_code=401, detail="Installation mismatch")
    if payload.get("fingerprint") != data.fingerprint:
        raise HTTPException(status_code=401, detail="Fingerprint mismatch")

    try:
        activation_id = UUID(payload["activation_id"])
        license_id = UUID(payload["license_id"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid license lease") from exc

    activation_result = await db.execute(select(Activation).where(Activation.id == activation_id))
    activation = activation_result.scalar_one_or_none()
    license_result = await db.execute(select(License).where(License.id == license_id))
    license = license_result.scalar_one_or_none()

    if not activation or not license or activation.license_id != license.id:
        raise HTTPException(status_code=404, detail="Activation not found")
    if activation.revoked_at:
        raise HTTPException(status_code=403, detail="Activation has been revoked")
    if activation.installation_id != data.installation_id or activation.fingerprint != data.fingerprint:
        raise HTTPException(status_code=401, detail="Installation mismatch")
    ensure_license_usable(license)

    activation.last_seen_at = utcnow()
    token, refresh_after, valid_until = issue_lease(license, activation)
    await db.commit()
    return LeaseResponse(
        lease_token=token,
        customer_name=license.customer_name,
        plan=license.plan,
        features=license.features or [],
        refresh_after=refresh_after,
        valid_until=valid_until,
        license_expires_at=license.expires_at,
    )


@app.post(
    "/admin/licenses",
    response_model=CreateLicenseResponse,
    dependencies=[Depends(require_admin)],
    status_code=status.HTTP_201_CREATED,
)
async def create_license(
    data: CreateLicenseRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    for _ in range(10):
        license_key = generate_license_key()
        key_hash = hash_license_key(license_key)
        duplicate = await db.scalar(select(func.count()).select_from(License).where(License.key_hash == key_hash))
        if not duplicate:
            break
    else:  # pragma: no cover
        raise HTTPException(status_code=500, detail="Could not generate unique license key")

    expires_at = utcnow() + timedelta(days=data.duration_days) if data.duration_days else None
    license = License(
        key_hash=key_hash,
        key_prefix=license_key[:11],
        customer_name=data.customer_name,
        plan=data.plan,
        status="active",
        expires_at=expires_at,
        max_activations=data.max_activations,
        features=data.features,
    )
    db.add(license)
    await db.commit()
    await db.refresh(license)
    return CreateLicenseResponse(
        id=license.id,
        customer_name=license.customer_name,
        plan=license.plan,
        status=license.status,
        expires_at=license.expires_at,
        max_activations=license.max_activations,
        features=license.features or [],
        key_prefix=license.key_prefix,
        active_activations=0,
        license_key=license_key,
    )


@app.get(
    "/admin/licenses",
    response_model=list[LicenseAdminResponse],
    dependencies=[Depends(require_admin)],
)
async def list_licenses(db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(License).order_by(License.created_at.desc()))
    rows = result.scalars().all()
    response: list[LicenseAdminResponse] = []
    for license in rows:
        active_count = await db.scalar(
            select(func.count()).select_from(Activation).where(
                Activation.license_id == license.id,
                Activation.revoked_at.is_(None),
            )
        )
        response.append(
            LicenseAdminResponse(
                id=license.id,
                customer_name=license.customer_name,
                plan=license.plan,
                status=license.status,
                expires_at=license.expires_at,
                max_activations=license.max_activations,
                features=license.features or [],
                key_prefix=license.key_prefix,
                active_activations=int(active_count or 0),
            )
        )
    return response


@app.post(
    "/admin/licenses/{license_id}/suspend",
    dependencies=[Depends(require_admin)],
)
async def suspend_license(
    license_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    license = await db.get(License, license_id)
    if not license:
        raise HTTPException(status_code=404, detail="License not found")
    license.status = "suspended"
    await db.commit()
    return {"status": "suspended"}


@app.post(
    "/admin/licenses/{license_id}/resume",
    dependencies=[Depends(require_admin)],
)
async def resume_license(
    license_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    license = await db.get(License, license_id)
    if not license:
        raise HTTPException(status_code=404, detail="License not found")
    if license.expires_at and license.expires_at <= utcnow():
        raise HTTPException(status_code=409, detail="Expired license cannot be resumed")
    license.status = "active"
    await db.commit()
    return {"status": "active"}


@app.post(
    "/admin/activations/{activation_id}/revoke",
    dependencies=[Depends(require_admin)],
)
async def revoke_activation(
    activation_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    activation = await db.get(Activation, activation_id)
    if not activation:
        raise HTTPException(status_code=404, detail="Activation not found")
    activation.revoked_at = utcnow()
    await db.commit()
    return {"status": "revoked"}
