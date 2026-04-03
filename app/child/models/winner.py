from typing import Optional
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.child.models import TournamentBase

class Winner(TournamentBase):
    __tablename__ = "winners"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    athlete_id: Mapped[Optional[int]] = mapped_column(ForeignKey("athletes.id"), nullable=True)
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"), nullable=True)
    
    # Место: 1, 2, 3 (или 3.1, 3.2 для двух бронз)
    # Используем Integer для простоты или Float, если нужны дробные места
    place: Mapped[int] = mapped_column(nullable=False)

    # Связи (Relationship)
    # Предполагается, что модели Athlete и Category уже определены
    athlete: Mapped[Optional["Athlete"]] = relationship()
    category: Mapped["Category"] = relationship(back_populates="winners")


    team: Mapped[Optional["Team"]] = relationship()

    # Уникальность: в одной категории не может быть двух одинаковых мест 
    # (если только это не заложено логикой двух бронз - тогда уберите это ограничение)

    __table_args__ = (
        UniqueConstraint('category_id', 'athlete_id', name='_athlete_category_uc'),
    )
