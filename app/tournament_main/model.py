from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Table, Column, ForeignKey, Float, Boolean
from datetime import date
from typing import List

class Base(DeclarativeBase):
    pass

class Tournament(Base):
    __tablename__ = "tournaments"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String)
    event_date: Mapped[date] = mapped_column(nullable=False)
    judge: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    secretary: Mapped[str] = mapped_column(String(255))
    db_path: Mapped[str] = mapped_column(String(255))  # Путь к файлу sqlite этого турнира


class CategoryTemplate(Base):
    __tablename__ = "category_templates"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100)) # "Юноши 12-13 лет"
    discipline: Mapped[str] = mapped_column(String(20), default="kata") # "kata"/"kumite"
    min_age: Mapped[int] = mapped_column(Integer)
    max_age: Mapped[int] = mapped_column(Integer)
    gender: Mapped[str] = mapped_column(String(10)) # "male"/"female"
    min_weight: Mapped[int] = mapped_column(nullable=True)
    max_weight: Mapped[int] = mapped_column(nullable=True)

# Прямая связь: список разрешенных ката для этого шаблона
    kata_associations: Mapped[list["CategoryKataTemplate"]] = relationship(back_populates="category")


class Kata(Base):
    __tablename__ = "katas"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False) 
    
    # Регламент времени (в секундах)
    min_duration: Mapped[float] = mapped_column(Float, default=0.0)
    max_duration: Mapped[float] = mapped_column(Float, default=300.0)
    
    # Флаг высшего ката
    is_advanced: Mapped[bool] = mapped_column(Boolean, default=False)

    category_associations: Mapped[list["CategoryKataTemplate"]] = relationship(back_populates="kata")

class CategoryKataTemplate(Base):
    __tablename__ = "category_template_kata_allowed"
    
    # ИСПРАВЛЕНО: ForeignKey должен указывать на 'category_templates.id'
    category_id: Mapped[int] = mapped_column(
        ForeignKey("category_templates.id", ondelete="CASCADE"), 
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
    category: Mapped["CategoryTemplate"] = relationship(back_populates="kata_associations")
