from typing import Optional
from sqlalchemy import ForeignKey, String, Table, Column, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.child.models import TournamentBase

class Team(TournamentBase):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=True) # Напр. "Клуб Алмаз-1"
    club: Mapped[str] = mapped_column(String(100), nullable=True) 

    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    
    # ДОБАВЬТЕ ЭТО ПОЛЕ:
    is_present: Mapped[bool] = mapped_column(Boolean, default=False)

    # Связь со спортсменами (3 человека)
    members: Mapped[list["Athlete"]] = relationship(secondary="team_members", primaryjoin="Team.id == team_members.c.team_id", secondaryjoin="Athlete.id == team_members.c.athlete_id", back_populates="team")
    # Ссылка на оценки (теперь Score может ссылаться либо на Athlete, либо на Team)
    scores: Mapped[list["Score"]] = relationship(back_populates="team")
# ДОБАВЬТЕ ЭТУ СТРОКУ (имя должно строго совпадать с back_populates в DraftAssignment)
    draft_assignments: Mapped[list["DraftAssignment"]] = relationship(back_populates="team", lazy="selectin")
    
# Таблица связи для состава команды
team_members = Table(
    "team_members",
    TournamentBase.metadata,
    Column("team_id", ForeignKey("teams.id"), primary_key=True),
    Column("athlete_id", ForeignKey("athletes.id"), primary_key=True)
)
