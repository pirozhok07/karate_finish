from typing import Optional
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.child.models import TournamentBase

class Score(TournamentBase):
    __tablename__ = "scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"), nullable=False)
    athlete_id: Mapped[Optional[int]] = mapped_column(ForeignKey("athletes.id"), nullable=True)
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"), nullable=True)
    
    # Оценки (от 5 до 7 судей)
    performance_kata: Mapped[str | None] = mapped_column(String(100), nullable=True)
    s1: Mapped[float] = mapped_column(default=0.0)
    s2: Mapped[float] = mapped_column(default=0.0)
    s3: Mapped[float] = mapped_column(default=0.0)
    s4: Mapped[float] = mapped_column(default=0.0)
    s5: Mapped[float] = mapped_column(default=0.0)
    
    total_score: Mapped[float] = mapped_column(default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    is_disqualified: Mapped[bool] = mapped_column(default=False)
    place: Mapped[int | None] = mapped_column(default=None)

    round: Mapped["Round"] = relationship(back_populates="scores")
    athlete: Mapped[Optional["Athlete"]] = relationship(back_populates="scores")
    team: Mapped[Optional["Team"]] = relationship(back_populates="scores")

    def __repr__(self) -> str:
        return f"<Performance Athlete {self.athlete_id} in Round {self.round_id}>"
    
    @property
    def scores_list(self):
        return [self.s1, self.s2, self.s3, self.s4, self.s5]
