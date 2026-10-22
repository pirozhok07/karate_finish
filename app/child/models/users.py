from app.child.models import TournamentBase
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import date

class User(TournamentBase):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(nullable=False)
    hashed_password: Mapped[str] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    is_admin: Mapped[bool] = mapped_column(default=False)
    role: Mapped[str] = mapped_column(default="user")
    

    