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
    weight: Mapped[float] = mapped_column(nullable=True)
    rank_kyu: Mapped[str | None] = mapped_column()     # Кю/Дан
    rank_sport: Mapped[str | None] = mapped_column()   # Разряд (КМС, 1-й юн. и т.д.)
    club: Mapped[str | None] = mapped_column()
    coach: Mapped[str | None] = mapped_column()        # Тренер
    is_present: Mapped[bool] = mapped_column(default=False) # Отметка о регистрации в день турнира
    registration_status: Mapped[str | None] = mapped_column(default="pending") # "confirmed", "absent"

    scores: Mapped[list["Score"]] = relationship("Score", back_populates="athlete")

    # ДОБАВЬТЕ ЭТУ СТРОКУ (имя должно строго совпадать с back_populates в DraftAssignment)
    draft_assignments: Mapped[list["DraftAssignment"]] = relationship(back_populates="athlete")
    