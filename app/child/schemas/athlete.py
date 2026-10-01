from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict
from datetime import date

from app.child.schemas.draft import DraftAssigmnentRead


# Базовая схема с общими полями для атлета
class AthleteBase(BaseModel):
    last_name: str
    first_name: str
    middle_name: str | None = None
    birth_date: date
    gender: str  # "male"/"female"
    rank_kyu: str | None = None
    rank_sport: str | None = None
    weight_preview: float | None = None
    weight_real: float | None = None
    club: str | None = None
    coach: str | None = None
    is_present: bool = False
    registration_status: str = "pending"

# Схема для POST-запроса (что присылает клиент)
class AthleteCreate(AthleteBase):
    pass

# Схема для ответа API (что видит клиент)
class AthleteRead(AthleteBase):
    id: int
    status: str
    is_present: bool
    team_statuses: Dict[int, bool]

    

    # Позволяет Pydantic считывать данные напрямую из объектов SQLAlchemy
    model_config = ConfigDict(from_attributes=True)

class AthleteGet(AthleteBase):
    id: int
    draft_assignments: List[DraftAssigmnentRead] = []
    model_config = ConfigDict(from_attributes=True)

# Схема для частичного обновления (PATCH запрос)
class AthleteUpdate(BaseModel):
    last_name: str | None = None
    first_name: str | None = None
    middle_name: str | None = None
    birth_date: date | None = None
    is_present: bool | None = None
    registration_status: str | None = None
    gender: str | None = None
    weight_preview: float | None = None
    weight_real: float | None = None
    rank_kyu: str | None = None
    rank_sport: str | None = None
    club: str | None = None
    coach: str | None = None
    removed_category_ids: Optional[List[int]] = None
    added_category_ids: Optional[List[int]] = None