from app.child.schemas.category import CategorySimple
from pydantic import BaseModel
from typing import Optional

class MatchResultUpdate(BaseModel):
    aka_score: int
    shiro_score: int
    winner_id: int
    is_finished: bool = True

class MatchResponse(BaseModel):
    id: int
    category: Optional[CategorySimple] = None 
    aka_id: Optional[int] = None
    shiro_id: Optional[int] = None
    aka_score: int =0
    shiro_score: int =0
    winner_id: Optional[int] = None
    is_finished: bool
    round_number: int
    number: int 

    class Config:
        from_attributes = True



class WinnerResponse(BaseModel):
    place: int
    athlete_id: int
    name: str
    points_scored: int # Сумма набранных баллов (для круговой системы)
