from fastapi import APIRouter
from pydantic import BaseModel

from aigentix.api.deps import CurrentUser
from aigentix.modules.base import ModuleStatus
from aigentix.modules.registry import MODULES

router = APIRouter(prefix="/modules", tags=["modules"])


class ModuleRead(BaseModel):
    key: str
    name: str
    description: str
    status: ModuleStatus


@router.get("", response_model=list[ModuleRead], operation_id="listModules")
def list_modules(_user: CurrentUser) -> list[ModuleRead]:
    return [ModuleRead(key=m.key, name=m.name, description=m.description, status=m.status) for m in MODULES]
