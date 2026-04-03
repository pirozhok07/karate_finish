from typing import Optional
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.child.models import TournamentBase

class Round(TournamentBase):
    __tablename__ = "rounds"
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    round_number: Mapped[int] = mapped_column(default=1) # 1, 2, 3...
    is_finished: Mapped[bool] = mapped_column(default=False)
    is_tie_break: Mapped[bool] = mapped_column(default=False)
    
    parent_round_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rounds.id")) 
    category: Mapped["Category"] = relationship(back_populates="rounds")
    # Оценки всех участников в этом конкретном круге
    scores: Mapped[list["Score"]] = relationship(
        back_populates="round", 
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Round {self.round_number} for Cat ID {self.category_id}>"