
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Category, SLAPolicy, Ticket
from app.schemas.category import (
    CategoryCreate,
    CategoryUpdate,
    CategoryResponse,
    SLAPolicyUpdate,
    SLAPolicyResponse,
)
from app.auth.security import require_roles


router = APIRouter(tags=["Categories and SLA Policies"])

VALID_PRIORITIES = ["Low", "Medium", "High", "Urgent"]


# CREATE CATEGORY
@router.post(
    "/categories",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    data: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_roles("Admin")),
):
    name = data.name.strip()

    if len(name) < 2:
        raise HTTPException(
            status_code=422,
            detail="Category name must contain at least 2 characters",
        )

    result = await db.execute(
        select(Category).where(func.lower(Category.name) == name.lower())
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Category already exists",
        )

    category = Category(
        name=name,
        description=data.description,
        is_active=True,
    )

    db.add(category)

    try:
        await db.commit()
        await db.refresh(category)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Category already exists",
        )

    return category


# GET ALL CATEGORIES
@router.get("/categories", response_model=list[CategoryResponse])
async def get_categories(
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_roles("Admin")),
):
    result = await db.execute(
        select(Category).order_by(Category.id)
    )
    return result.scalars().all()


# UPDATE CATEGORY
@router.put(
    "/categories/{category_id}",
    response_model=CategoryResponse,
)
async def update_category(
    category_id: int,
    data: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_roles("Admin")),
):
    result = await db.execute(
        select(Category).where(Category.id == category_id)
    )
    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=404,
            detail="Category not found",
        )

    updates = data.model_dump(exclude_unset=True)

    if "name" in updates:
        if updates["name"] is None:
            updates.pop("name")
        else:
            updates["name"] = updates["name"].strip()

            if len(updates["name"]) < 2:
                raise HTTPException(
                    status_code=422,
                    detail="Category name must contain at least 2 characters",
                )

            duplicate_result = await db.execute(
                select(Category).where(
                    func.lower(Category.name) == updates["name"].lower(),
                    Category.id != category_id,
                )
            )

            if duplicate_result.scalar_one_or_none():
                raise HTTPException(
                    status_code=409,
                    detail="Another category already uses this name",
                )

    for field, value in updates.items():
        setattr(category, field, value)

    try:
        await db.commit()
        await db.refresh(category)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Category name already exists",
        )

    return category


# DELETE CATEGORY
@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_roles("Admin")),
):
    result = await db.execute(
        select(Category).where(Category.id == category_id)
    )
    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=404,
            detail="Category not found",
        )

    open_ticket_result = await db.execute(
        select(func.count(Ticket.id)).where(
            Ticket.category_id == category_id,
            Ticket.status.not_in(["Resolved", "Closed"]),
        )
    )

    open_ticket_count = open_ticket_result.scalar_one()

    if open_ticket_count > 0:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a category that has open tickets",
        )

    await db.delete(category)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Category is being used by existing records. Deactivate it instead.",
        )

    return {"message": "Category deleted successfully"}


# GET ALL SLA POLICIES
@router.get(
    "/sla-policies",
    response_model=list[SLAPolicyResponse],
)
async def get_sla_policies(
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_roles("Admin")),
):
    result = await db.execute(
        select(SLAPolicy).order_by(SLAPolicy.id)
    )
    return result.scalars().all()


# CREATE OR UPDATE AN SLA POLICY
@router.put(
    "/sla-policies/{priority}",
    response_model=SLAPolicyResponse,
)
async def upsert_sla_policy(
    priority: str,
    data: SLAPolicyUpdate,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_roles("Admin")),
):
    normalized_priority = priority.strip().title()

    if normalized_priority not in VALID_PRIORITIES:
        raise HTTPException(
            status_code=422,
            detail="Priority must be Low, Medium, High, or Urgent",
        )

    result = await db.execute(
        select(SLAPolicy).where(
            SLAPolicy.priority == normalized_priority
        )
    )
    policy = result.scalar_one_or_none()

    if policy is None:
        policy = SLAPolicy(
            priority=normalized_priority,
            first_response_minutes=data.first_response_minutes,
            resolution_minutes=data.resolution_minutes,
        )
        db.add(policy)
    else:
        policy.first_response_minutes = data.first_response_minutes
        policy.resolution_minutes = data.resolution_minutes

    try:
        await db.commit()
        await db.refresh(policy)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Could not save the SLA policy",
        )

    return policy
