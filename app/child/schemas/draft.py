from typing import Optional
from pydantic import BaseModel, ConfigDict

from app.child.schemas.category import CategoryRead

class DraftAssigmnentRead(BaseModel):
    id: int
    category_id: Optional[int] = None
    category: Optional[CategoryRead] = None

    model_config = ConfigDict(from_attributes=True)

class DraftAdd(BaseModel):
    athleteId: Optional[int] = None
    teamId: Optional[int] = None
    categoryId: int
