from pydantic import BaseModel, EmailStr, Field
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.auth import InitialAdminRequest, RegisterRequest, TokenResponse, UserResponse, LoginRequest
from app.auth.security import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/setup-initial-admin", status_code=201)
async def setup_initial_admin(
    data: InitialAdminRequest,
    db: AsyncSession = Depends(get_db),
):
    # Only allow this setup while the database has no users.
    result = await db.execute(select(User.id).limit(1))

    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=403,
            detail="Initial Admin setup is disabled because users already exist",
        )

    admin = User(
        full_name=data.full_name.strip(),
        email=str(data.email).strip().lower(),
        hashed_password=hash_password(data.password),
        role="Admin",
        is_active=True,
    )

    db.add(admin)

    try:
        await db.commit()
        await db.refresh(admin)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Could not create the initial Admin",
        )

    return {
        "message": "Initial Admin created successfully",
        "admin_id": admin.id,
        "email": admin.email,
        "role": admin.role,
    }


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    user_data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.email == user_data.email)
    )
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    new_user = User(
        full_name=user_data.full_name,
        email=str(user_data.email).lower(),
        hashed_password=hash_password(user_data.password),
        role="Customer",
        is_active=True,
    )

    db.add(new_user)

    try:
        await db.commit()
        await db.refresh(new_user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    return new_user



@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    email = data.email.strip().lower()

    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()

    if (
        user is None
        or not verify_password(data.password, user.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is inactive",
        )

    access_token = create_access_token(user)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user,
    }


@router.get("/me", response_model=UserResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    return current_user
