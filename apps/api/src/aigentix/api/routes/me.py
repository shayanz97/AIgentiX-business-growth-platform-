from fastapi import APIRouter
from pydantic import BaseModel

from aigentix.api.deps import CurrentUser, DbSession
from aigentix.api.schemas import MembershipRead, OrganizationRead, UserRead
from aigentix.platform.organizations.service import list_memberships_for_user

router = APIRouter(tags=["me"])


class MeResponse(BaseModel):
    user: UserRead
    memberships: list[MembershipRead]


@router.get("/me", response_model=MeResponse, operation_id="getMe")
def me(user: CurrentUser, db: DbSession) -> MeResponse:
    memberships = [
        MembershipRead(organization=OrganizationRead.model_validate(m.organization), role=m.role)
        for m in list_memberships_for_user(db, user)
    ]
    return MeResponse(user=UserRead.model_validate(user), memberships=memberships)
