from pydantic import BaseModel, ConfigDict
from datetime import date

# Базовая схема с общими полями
class TournamentBase(BaseModel):
    title: str
    type: str
    description: str
    judge: str
    secretary: str
    event_date: date

# Схема для создания (то, что присылает клиент)
class TournamentCreate(TournamentBase):
    template_ids: list[int] 
    pass

# Схема для ответа (то, что возвращает API клиенту)
class TournamentRead(TournamentBase):
    id: int
    db_path: str

    # Позволяет Pydantic работать с объектами SQLAlchemy (через .id, .title)
    model_config = ConfigDict(from_attributes=True)

# Схема для обновления (все поля опциональны)
class TournamentUpdate(BaseModel):
    title: str | None = None
    event_date: date | None = None


class CategoryTemplateRead(BaseModel):
    id: int
    name: str
    min_age: int
    max_age: int
    gender: str

    model_config = ConfigDict(from_attributes=True)