from pydantic import BaseModel
from typing import List, Optional

class ScoreUpdate(BaseModel):
    performance_kata: Optional[str] = None
    s1: float = 0.0
    s2: float = 0.0
    s3: float = 0.0
    s4: float = 0.0
    s5: float = 0.0

class OrderItem(BaseModel):
    # athlete_id: int
    score_id: int
    position: int


class OrderUpdate(BaseModel):
    order: List[OrderItem]