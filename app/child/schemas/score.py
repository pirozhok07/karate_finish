from pydantic import BaseModel
from typing import Optional

class ScoreUpdate(BaseModel):
    performance_kata: Optional[str] = None
    s1: float = 0.0
    s2: float = 0.0
    s3: float = 0.0
    s4: float = 0.0
    s5: float = 0.0