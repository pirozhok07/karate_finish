from sqlalchemy import ForeignKey, Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.child.models import TournamentBase

class Match(TournamentBase):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    
    # Ссылки на участников (предполагаем, что таблица участников — participants)
    aka_id: Mapped[int | None] = mapped_column(ForeignKey("athletes.id"), nullable=True)
    shiro_id: Mapped[int | None] = mapped_column(ForeignKey("athletes.id"), nullable=True)
    
    
    # Логика боя
    number: Mapped[int] = mapped_column(Integer)  # Номер боя 
    number_for_tatami: Mapped[int] = mapped_column(Integer, nullable=True)  # Номер боя в сетке
    round_number: Mapped[int] = mapped_column(Integer, default=1)  # 1/8, 1/4, финал и т.д.
    
    # Результаты
    aka_score: Mapped[int] = mapped_column(Integer, default=0)
    shiro_score: Mapped[int] = mapped_column(Integer, default=0)
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("athletes.id"), nullable=True)
    is_finished: Mapped[bool] = mapped_column(Boolean, default=False)
    is_repechage: Mapped[bool] = mapped_column(Boolean, default=False)

    # Новые поля для связи "дерева"
    next_match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"))
    # Позиция в следующем матче: 1 (AKA) или 2 (SHIRO)
    next_match_position: Mapped[int | None] = mapped_column(Integer)
    # Связи
    category: Mapped["Category"] = relationship(back_populates="matches")
    aka: Mapped["Athlete"] = relationship("Athlete", foreign_keys=[aka_id], lazy="selectin")
    shiro: Mapped["Athlete"] = relationship("Athlete", foreign_keys=[shiro_id], lazy="selectin")

    def to_dict(self):
        return{
            "id": self.id,
            "category_id": self.category_id,
            "aka_id": self.aka_id,
            "shiro_id": self.shiro_id,
            "aka": self.aka.to_dict() if self.aka else None,
            "shiro": self.shiro.to_dict() if self.shiro else None,
            "number_for_tatami": self.number_for_tatami,
            "number": self.number,
            "round_number": self.round_number,
            "winner_id": self.winner_id,
            "is_finished": self.is_finished,
            "is_repechage": self.is_repechage,
        }
