import json
import os
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.tournament_main.model import CategoryKataTemplate, CategoryTemplate, Kata
from app.tournament_main.template import CATEGORIES # Список категорий можно вынести в конфиг
from app.core.logger import logger

# async def setup_initial_templates(session: AsyncSession):
#     """Проверяет наличие шаблонов и добавляет их, если таблица пуста."""
#     result = await session.execute(select(CategoryTemplate).limit(1))
#     exists = result.scalar_one_or_none()

#     if not exists:
#         templates = [
#             CategoryTemplate(
#                 name=cat["name"],
#                 min_age=cat["min_age"],
#                 max_age=cat["max_age"],
#                 gender=cat["gender"]
#             ) for cat in CATEGORIES
#         ]
#         session.add_all(templates)
#         await session.commit()
#         # logger.info("Шаблоны категорий успешно добавлены в основную БД")

async def setup_initial_templates(db: AsyncSession):
    # Проверяем, не пуста ли база, чтобы не дублировать данные
    result = await db.execute(select(Kata).limit(1))
    if result.scalar_one_or_none():
        return # База уже заполнена

    file_path = r"data\initial_data.json"
    
    if not os.path.exists(file_path):
        logger.info(" not")
        return
    print(1)
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. Заполняем Ката
    katas_map = {}
    for k_data in data["katas"]:
        kata = Kata(**k_data)
        db.add(kata)
        katas_map[kata.name] = kata
    
    await db.flush() # Получаем ID для ката

    # 2. Заполняем Шаблоны Категорий
    for t_data in data["category_templates"]:
        # Извлекаем список имен ката, чтобы не передать лишнего в конструктор модели
        first_round_names = t_data.pop("allowed_kata_names", [])
        second_round_names = t_data.pop("allowed_kata_names_second", [])
        
        template = CategoryTemplate(**t_data)
        db.add(template)
        await db.flush() # Получаем ID шаблона

        # Привязываем объекты Ката по именам из нашего словаря
        # ЛОГИКА СВЯЗЕЙ:
        if not second_round_names:
            # СЛУЧАЙ А: Один список на все круги (round_limit = 0)
            for name in first_round_names:
                if name in katas_map:
                    assoc = CategoryKataTemplate(
                        category_id=template.id,
                        kata_id=katas_map[name].id,
                        round_limit=0
                    )
                    db.add(assoc)
        else:
            # СЛУЧАЙ Б: Разные списки
            # 1 круг (round_limit = 1)
            for name in first_round_names:
                if name in katas_map:
                    assoc = CategoryKataTemplate(
                        category_id=template.id,
                        kata_id=katas_map[name].id,
                        round_limit=1
                    )
                    db.add(assoc)
            
            # 2 и 3 круги (round_limit = 2)
            for name in second_round_names:
                if name in katas_map:
                    assoc = CategoryKataTemplate(
                        category_id=template.id,
                        kata_id=katas_map[name].id,
                        round_limit=2
                    )
                    db.add(assoc)

    await db.commit()
    print("Данные успешно инициализированы!")