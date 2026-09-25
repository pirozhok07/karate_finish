from app.child.schemas.category import CategorySimple
from pydantic import BaseModel
from typing import Optional

class AthleteResponse(BaseModel):
    id: int
    last_name: str
    first_name: str
    club: str

class MatchResultUpdate(BaseModel):
    winner_id: int
    is_finished: bool = True

class TatamiNumberCreate(BaseModel):
    category_id: Optional[int] = None
    tatami_id: int

class TatamiNumberCreateResponce(BaseModel):
    category_id: int
    name: str
    count: int

class MatchResponse(BaseModel):
    id: int
    category: Optional[CategorySimple] = None 
    aka_id: Optional[int] = None
    shiro_id: Optional[int] = None
    winner_id: Optional[int] = None
    is_finished: bool
    round_number: int
    number: int 
    aka: Optional[AthleteResponse] = None
    shiro: Optional[AthleteResponse] = None

    class Config:
        from_attributes = True


class WinnerResponse(BaseModel):
    place: int
    athlete_id: int
    name: str
    points_scored: int # Сумма набранных баллов (для круговой системы)
