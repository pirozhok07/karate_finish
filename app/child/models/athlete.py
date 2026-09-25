from app.child.models import TournamentBase
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import date

class Athlete(TournamentBase):
    __tablename__ = "athletes"

    id: Mapped[int] = mapped_column(primary_key=True)
    last_name: Mapped[str] = mapped_column(nullable=False)
    first_name: Mapped[str] = mapped_column(nullable=False)
    middle_name: Mapped[str | None] = mapped_column()
    birth_date: Mapped[date] = mapped_column(nullable=False)
    gender: Mapped[str] = mapped_column(nullable=False) # "male"/"female"
    weight_preview: Mapped[float] = mapped_column(nullable=True)
    weight_real: Mapped[float] = mapped_column(nullable=True)
    rank_kyu: Mapped[str | None] = mapped_column()     # Кю/Дан
    rank_sport: Mapped[str | None] = mapped_column()   # Разряд (КМС, 1-й юн. и т.д.)
    club: Mapped[str | None] = mapped_column()
    coach: Mapped[str | None] = mapped_column()        # Тренер
    is_present: Mapped[bool] = mapped_column(default=False) # Отметка о регистрации в день турнира
    registration_status: Mapped[str | None] = mapped_column(default="pending") # "confirmed", "absent"
    
    is_kata: Mapped[bool] = mapped_column(default=False) 
    is_team: Mapped[bool] = mapped_column(default=False) 
    is_kumite: Mapped[bool] = mapped_column(default=False) 

    scores: Mapped[list["Score"]] = relationship("Score", back_populates="athlete")

    # ДОБАВЬТЕ ЭТУ СТРОКУ (имя должно строго совпадать с back_populates в DraftAssignment)
    draft_assignments: Mapped[list["DraftAssignment"]] = relationship(back_populates="athlete", lazy="selectin")
    team: Mapped[list["Team"]] = relationship(secondary="team_members", primaryjoin="Athlete.id == team_members.c.athlete_id", secondaryjoin="Team.id == team_members.c.team_id", lazy="selectin", back_populates="members")

    @property
    def age(self):
        today = date.today()
        return today.year-self.birth_date.year - (
            (today.month,today.day) < (self.birth_date.month, self.birth_date.day)
        )

    def to_dict(self):
        return{
            "id": self.id,
            "last_name": self.last_name,
            "first_name": self.first_name,
            "club": self.club,
        }
    
    def __repr__(self) -> str:
        return f"<Athlete {self.last_name}>"