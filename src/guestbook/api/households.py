"""Household API routes."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guestbook.api.deps import get_current_user, get_db
from guestbook.models.household import Household, HouseholdMember
from guestbook.models.user import User
from guestbook.schemas.household import (
    HouseholdCreate,
    HouseholdMemberCreate,
    HouseholdMemberResponse,
    HouseholdResponse,
)

router = APIRouter(prefix="/household", tags=["household"])


@router.get("", response_model=HouseholdResponse | None)
async def get_household(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the current user's household."""
    if current_user.household_id is None:
        return None
    result = await db.execute(
        select(Household).where(Household.id == current_user.household_id)
    )
    return result.scalar_one_or_none()


@router.post("", response_model=HouseholdResponse, status_code=201)
async def create_household(
    body: HouseholdCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Household:
    """Create a household. The user is automatically added as a member."""
    if current_user.household_id is not None:
        raise HTTPException(status_code=409, detail="You already belong to a household")

    household = Household(name=body.name)
    db.add(household)
    await db.flush()

    # Add the user as a member
    member = HouseholdMember(
        household_id=household.id,
        user_id=current_user.id,
        name=current_user.display_name or current_user.email,
        food_preference=current_user.food_preference,
        dietary_restrictions=current_user.dietary_restrictions,
        alcohol=current_user.alcohol,
    )
    db.add(member)

    # Link user to household
    result = await db.execute(select(User).where(User.id == current_user.id))
    db_user = result.scalar_one()
    db_user.household_id = household.id

    await db.commit()
    await db.refresh(household)
    return household


@router.post("/join/{invite_code}", response_model=HouseholdResponse)
async def join_household(
    invite_code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Household:
    """Join a household by invite code."""
    if current_user.household_id is not None:
        raise HTTPException(status_code=409, detail="You already belong to a household")

    result = await db.execute(
        select(Household).where(Household.invite_code == invite_code)
    )
    household = result.scalar_one_or_none()
    if household is None:
        raise HTTPException(status_code=404, detail="Invalid invite code")

    # Add as member
    member = HouseholdMember(
        household_id=household.id,
        user_id=current_user.id,
        name=current_user.display_name or current_user.email,
        food_preference=current_user.food_preference,
        dietary_restrictions=current_user.dietary_restrictions,
        alcohol=current_user.alcohol,
    )
    db.add(member)

    # Link user
    result = await db.execute(select(User).where(User.id == current_user.id))
    db_user = result.scalar_one()
    db_user.household_id = household.id

    await db.commit()
    await db.refresh(household)
    return household


@router.get("/members", response_model=list[HouseholdMemberResponse])
async def list_members(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[HouseholdMember]:
    """List members of the current user's household."""
    if current_user.household_id is None:
        return []
    result = await db.execute(
        select(HouseholdMember)
        .where(HouseholdMember.household_id == current_user.household_id)
        .order_by(HouseholdMember.created_at)
    )
    return list(result.scalars().all())


@router.post("/members", response_model=HouseholdMemberResponse, status_code=201)
async def add_member(
    body: HouseholdMemberCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HouseholdMember:
    """Add a member to the household (unlinked — just a name)."""
    if current_user.household_id is None:
        raise HTTPException(status_code=400, detail="You don't belong to a household")

    member = HouseholdMember(
        household_id=current_user.household_id,
        name=body.name,
        food_preference=body.food_preference,
        dietary_restrictions=body.dietary_restrictions,
        alcohol=body.alcohol,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@router.delete("/members/{member_id}", status_code=204)
async def remove_member(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Remove a member from the household."""
    if current_user.household_id is None:
        raise HTTPException(status_code=400, detail="You don't belong to a household")

    result = await db.execute(
        select(HouseholdMember).where(
            HouseholdMember.id == member_id,
            HouseholdMember.household_id == current_user.household_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")

    # Don't allow removing yourself if you're the linked user
    if member.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't remove yourself. Leave the household instead.")

    await db.delete(member)
    await db.commit()
