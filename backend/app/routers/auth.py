"""Auth endpoints — login and "who am I".

Login is an unauthenticated route, so it can't use `get_current_user` to
install tenant context. It does the lookup as a platform_admin-bypassing
context so it can find users across orgs by email — then on successful
password check it issues a JWT whose claims pin the user's org for every
subsequent request.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, set_tenant_context
from app.deps import get_current_user
from app.models import User
from app.security import hash_password, issue_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Decoy hash used on the "email not found" branch so verify_password runs in
# both branches and timing doesn't leak which half failed. Hashing a secret
# at import once keeps the cost comparable to a real verify.
_TIMING_SAFE_DECOY_HASH = hash_password("not-a-real-password")


class LoginRequest(BaseModel):
    # Plain str on purpose — validating email format at login serves no
    # purpose (the DB lookup either finds a match or doesn't); stricter
    # EmailStr validation lives on user-creation endpoints where it matters.
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    org_id: str | None
    is_primary_admin: bool

    @classmethod
    def from_orm(cls, user: User) -> UserOut:
        return cls(
            id=str(user.id),
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            org_id=str(user.org_id) if user.org_id else None,
            is_primary_admin=user.is_primary_admin,
        )


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LoginResponse:
    # Login must look up users by email across all orgs, so run the lookup
    # under a platform_admin context. The RLS policy on `users` lets
    # platform_admin see every row; we still run under the non-superuser
    # app_user role, so the policy actually applies (not a bypass via
    # superuser).
    await set_tenant_context(session, role="platform_admin")

    user = (
        await session.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()

    hash_to_check = user.password_hash if user is not None else _TIMING_SAFE_DECOY_HASH
    password_ok = verify_password(payload.password, hash_to_check)

    if user is None or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        )

    token, _expires_at = issue_token(user_id=user.id, role=user.role, org_id=user.org_id)
    return LoginResponse(access_token=token, user=UserOut.from_orm(user))


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(get_current_user)]) -> UserOut:
    return UserOut.from_orm(user)
