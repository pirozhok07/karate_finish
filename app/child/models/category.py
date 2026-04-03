from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, ForeignKey, Table, Float, Boolean
from app.child.models import TournamentBase

class Category(TournamentBase):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False) # Напр. "Мальчики 8-9 лет"
    discipline: Mapped[str] = mapped_column(String(20), default="kata") # "kata"/"kumite"
    
    min_age: Mapped[int] = mapped_column(nullable=False)
    max_age: Mapped[int] = mapped_column(nullable=False)
    gender: Mapped[str] = mapped_column(String(10), nullable=False) # "male"/"female"
    min_weight: Mapped[int] = mapped_column(nullable=True)
    max_weight: Mapped[int] = mapped_column(nullable=True)

    # Связь для КАТА (используется только если discipline == "kata")
    rounds: Mapped[list["Round"]] = relationship(back_populates="category")

    # Связь для КУМИТЕ (используется только если discipline == "kumite")
    matches: Mapped[list["Match"]] = relationship(back_populates="category")
    winners: Mapped[list["Winner"]] = relationship(
        back_populates="category", 
        cascade="all, delete-orphan"
    )
    draft_assignments: Mapped[list["DraftAssignment"]] = relationship(back_populates="category")

    # Прямая связь: список разрешенных ката для этого шаблона
    kata_associations: Mapped[list["CategoryKata"]] = relationship(back_populates="category")

    def __repr__(self) -> str:
        return f"<Category {self.name}>"



class Kata(TournamentBase):
    __tablename__ = "katas"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False) 
    
    # Регламент времени (в секундах)
    min_duration: Mapped[float] = mapped_column(Float, default=0.0)
    max_duration: Mapped[float] = mapped_column(Float, default=300.0)
    
    # Флаг высшего ката
    is_advanced: Mapped[bool] = mapped_column(Boolean, default=False)
    
    category_associations: Mapped[list["CategoryKata"]] = relationship(back_populates="kata")


class CategoryKata(TournamentBase):
    __tablename__ = "category_kata_allowed"
    
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), 
        primary_key=True
    )
    kata_id: Mapped[int] = mapped_column(
        ForeignKey("katas.id", ondelete="CASCADE"), 
        primary_key=True
    )
    
    # 0 = везде, 1 = 1-й круг, 2 = 2 и 3 круги
    round_limit: Mapped[int] = mapped_column(Integer, default=0, primary_key=True)

    # Связи для удобного доступа
    kata: Mapped["Kata"] = relationship(back_populates="category_associations")
    category: Mapped["Category"] = relationship(back_populates="kata_associations")
