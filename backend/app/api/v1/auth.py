from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.config import settings
from app.db import db
from app.security import create_access_token, create_refresh_token, get_current_user, hash_password, verify_password
from app.security_controls import rate_limit

router = APIRouter(tags=["auth"])


class UserRegister(BaseModel):
    email: EmailStr
    full_name: str
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/register", dependencies=[Depends(rate_limit(5, 60))])
async def register_user(payload: UserRegister) -> dict[str, Any]:
    existing = db.users.find_one({"email": payload.email})
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists")

    user_doc = {
        "email": payload.email,
        "full_name": payload.full_name,
        "password": hash_password(payload.password),
        "role": "CUSTOMER",
        "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    }
    db.users.insert_one(user_doc)
    return {"message": "User registered successfully"}


@router.post("/login", dependencies=[Depends(rate_limit(10, 60))])
async def login(payload: UserLogin) -> dict[str, Any]:
    user = db.users.find_one({"email": payload.email})
    if not user or not verify_password(payload.password, user["password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token = create_access_token(subject=user["email"], role=user["role"])
    refresh_token = create_refresh_token(subject=user["email"], role=user["role"])
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {"email": user["email"], "role": user["role"], "full_name": user["full_name"]},
    }


@router.post("/refresh", dependencies=[Depends(rate_limit(10, 60))])
async def refresh_token(payload: RefreshRequest) -> dict[str, Any]:
    from jose import JWTError, jwt

    try:
        token_payload = jwt.decode(payload.refresh_token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc

    if token_payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user = db.users.find_one({"email": token_payload.get("sub")})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {"access_token": create_access_token(user["email"], user["role"]), "token_type": "bearer"}


@router.get("/me")
async def get_me(current_user: dict = __import__("fastapi").Depends(get_current_user)) -> dict[str, Any]:
    return {"user": {"email": current_user["email"], "role": current_user["role"], "full_name": current_user.get("full_name")}}
