from typing import Optional
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.child.models import TournamentBase

class DraftAssignment(TournamentBase):
    __tablename__ = "draft_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Личный зачет
    athlete_id: Mapped[Optional[int]] = mapped_column(ForeignKey("athletes.id"), nullable=True)
    
    #  ДЛЯ КОМАНД:
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"), nullable=True)
    
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    
    # Причина, если категория не найдена автоматически
    reason: Mapped[str | None] = mapped_column(String(200))

    athlete: Mapped[Optional["Athlete"]] = relationship(back_populates="draft_assignments")
    team: Mapped[Optional["Team"]] = relationship() # Связь с командой
    
    category: Mapped["Category"] = relationship()
