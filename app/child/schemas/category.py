from pydantic import BaseModel, ConfigDict
from datetime import date

# Базовая схема с общими полями для 
class CategoryBase(BaseModel):
    name: str
    min_age: int
    max_age: int 
    gender: str  # "male"/"female"

# # Схема для POST-запроса (что присылает клиент)
# class CategoryCreate(CategoryBase):
#     pass

# Схема для ответа API (что видит клиент)
class CategoryRead(CategoryBase):
    id: int

    # Позволяет Pydantic считывать данные напрямую из объектов SQLAlchemy
    model_config = ConfigDict(from_attributes=True)

class CategorySimple(BaseModel):
    id: int
    name: str
# # Схема для частичного обновления (PATCH запрос)
# class CategoryUpdate(BaseModel):
#     last_name: str | None = None
#     first_name: str | None = None
#     middle_name: str | None = None
#     birth_date: date | None = None
#     is_present: bool | None = None
#     registration_status: str | None = None
