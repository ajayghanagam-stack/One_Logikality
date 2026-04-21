"""Packet upload API (US-3.1 / US-3.2 / US-3.3).

`POST /api/packets` — multipart/form-data: one or more `files` plus the
declared loan program. Every authenticated customer role (admin and
user) can upload; reads are org-scoped via RLS. The declared program is
persisted on the row so rule resolution at processing time stays
reproducible even if org config changes mid-flight.

The ECV pipeline itself lands in the next slice; this endpoint leaves
packets in `status='uploaded'` and returns the created row. A later
slice will attach the Temporal workflow and flip the status through
`processing` → `completed` / `failed`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.storage_local import get_storage
from app.db import get_session
from app.deps import require_customer_role
from app.models import Packet, PacketFile, User
from app.rules import LOAN_PROGRAM_IDS

router = APIRouter(prefix="/api/packets", tags=["packets"])

# 100 MB per file. Arbitrary but generous for mortgage packets; a 2,000-
# page scanned PDF at typical density is well under that. Revisit when
# we have real ingest traffic.
_MAX_FILE_BYTES = 100 * 1024 * 1024

# Accept the extensions the demo's upload page advertises. Content-type
# is unreliable for PDFs coming through different browsers, so we filter
# on file extension and trust the byte stream behind it.
_ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


class PacketFileOut(BaseModel):
    id: str
    filename: str
    size_bytes: int
    content_type: str


class PacketOut(BaseModel):
    id: str
    declared_program_id: str
    status: str
    created_at: datetime
    files: list[PacketFileOut]


def _extension(filename: str) -> str:
    # Lowercase last segment after the final dot. Guards against "UPPER.PDF".
    _, _, ext = filename.rpartition(".")
    return f".{ext.lower()}" if ext else ""


@router.post("", response_model=PacketOut, status_code=status.HTTP_201_CREATED)
async def create_packet(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
    declared_program_id: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
) -> PacketOut:
    if declared_program_id not in LOAN_PROGRAM_IDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown program id {declared_program_id!r}",
        )
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="at least one file is required",
        )

    # Read everything before we touch the DB — if any file is oversized
    # or has a disallowed extension we reject cleanly with 400 and don't
    # leave a half-built packet around.
    buffered: list[tuple[UploadFile, bytes]] = []
    for upload in files:
        name = upload.filename or ""
        if _extension(name) not in _ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unsupported file type: {name!r}",
            )
        data = await upload.read()
        if len(data) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"empty file: {name!r}",
            )
        if len(data) > _MAX_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"file too large: {name!r}",
            )
        buffered.append((upload, data))

    # RLS guarantees org_id would be own-org anyway, but we set it
    # explicitly so the row is valid even when tests bypass RLS by
    # connecting as the postgres superuser.
    assert user.org_id is not None  # customer roles always carry an org
    packet = Packet(
        org_id=user.org_id,
        declared_program_id=declared_program_id,
        status="uploaded",
        created_by=user.id,
    )
    session.add(packet)
    await session.flush()  # populate packet.id before child rows reference it

    storage = get_storage()
    file_rows: list[PacketFile] = []
    for upload, data in buffered:
        file_id = uuid.uuid4()
        # Namespaced under org/packet so a single storage root can serve
        # every tenant without leaking keys; the file_id prefix makes
        # collisions from repeated filenames impossible.
        safe_name = (upload.filename or "file").replace("/", "_")
        key = f"packets/{packet.org_id}/{packet.id}/{file_id}__{safe_name}"
        await storage.put(key, data)

        file_rows.append(
            PacketFile(
                id=file_id,
                packet_id=packet.id,
                org_id=packet.org_id,
                filename=safe_name,
                size_bytes=len(data),
                content_type=upload.content_type or "application/octet-stream",
                storage_key=key,
            )
        )
    session.add_all(file_rows)
    await session.commit()
    await session.refresh(packet)

    return PacketOut(
        id=str(packet.id),
        declared_program_id=packet.declared_program_id,
        status=packet.status,
        created_at=packet.created_at,
        files=[
            PacketFileOut(
                id=str(f.id),
                filename=f.filename,
                size_bytes=f.size_bytes,
                content_type=f.content_type,
            )
            for f in file_rows
        ],
    )


@router.get("/{packet_id}", response_model=PacketOut)
async def get_packet(
    packet_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> PacketOut:
    packet = (
        await session.execute(select(Packet).where(Packet.id == packet_id))
    ).scalar_one_or_none()
    if packet is None:
        # Could be "not yours" (RLS filtered it) or "doesn't exist" — we
        # return 404 in both cases so the API doesn't leak existence
        # across tenants.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="packet not found")

    files = (
        (await session.execute(select(PacketFile).where(PacketFile.packet_id == packet_id)))
        .scalars()
        .all()
    )
    return PacketOut(
        id=str(packet.id),
        declared_program_id=packet.declared_program_id,
        status=packet.status,
        created_at=packet.created_at,
        files=[
            PacketFileOut(
                id=str(f.id),
                filename=f.filename,
                size_bytes=f.size_bytes,
                content_type=f.content_type,
            )
            for f in files
        ],
    )
