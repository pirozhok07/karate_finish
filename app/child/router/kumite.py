from typing import List
from app.child.models.athlete import Athlete
from app.child.models.match import Match
from app.child.services.service import create_finals_and_third_place, generate_all_kumite_horizontal,  generate_full_bracket, generate_kumite_bracket, generate_next_round, get_category_winners
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_t_db # Ваша зависимость БД
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from app.child.schemas.match import MatchResponse, MatchResultUpdate


router = APIRouter(prefix="/{tournament_id}/kumite", tags=["Kumite"])

@router.post("/generate-all")
async def generate_all(tournament_id: int, t_db: AsyncSession = Depends(get_t_db)):
    # Удаляем старые матчи кумите, если они были
    await t_db.execute(delete(Match))
    return await generate_all_kumite_horizontal(tournament_id, t_db)

# 1. Генерация первого круга сетки
@router.post("/generate/{category_id}")
async def generate_matches(category_id: int, t_db: AsyncSession = Depends(get_t_db)):
    # Проверяем, есть ли уже матчи, чтобы не дублировать
    existing = await t_db.execute(select(Match).where(Match.category_id == category_id))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Сетка уже сгенерирована")
    
    # Вызываем логику распределения (из предыдущего шага)
    
    await generate_full_bracket(category_id, t_db)
    # await generate_kumite_bracket(category_id, t_db)
    return {"status": "Сетка создана"}

# 1. Получить матчи ОДНОЙ категории
@router.get("/{category/{category_id}", response_model=list[MatchResponse])
async def get_category_matches(category_id: int, t_db: AsyncSession = Depends(get_t_db)):
    result = await t_db.execute(
        select(Match).where(Match.category_id == category_id).order_by(Match.number)
    )
    return result.scalars().all()

# 2. Получить ВЕСЬ поток турнира (Все категории по порядку номеров)
@router.get("/stream/all", response_model=list[MatchResponse])
async def get_full_tournament_stream(t_db: AsyncSession = Depends(get_t_db)):
    result = await t_db.execute(
        select(Match).options(selectinload(Match.category)).order_by(Match.number) # Сквозная нумерация
    )
    return result.scalars().all()


# 2. Получение всех матчей категории (для визуализации в Swagger)
@router.get("/{category_id}", response_model=List[MatchResponse])
async def get_matches(category_id: int, t_db: AsyncSession = Depends(get_t_db)):
    result = await t_db.execute(
        select(Match).where(Match.category_id == category_id).order_by(Match.round_number, Match.number)
    )
    return result.scalars().all()

@router.patch("/match/{match_id}")
async def update_match_score(match_id: int, data: MatchResultUpdate, t_db: AsyncSession= Depends(get_t_db)):
     # 1. Получаем текущий матч
    match = await t_db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Матч не найден")
    
    # Сохраняем результат
    match.aka_score = data.aka_score
    match.shiro_score = data.shiro_score
    match.winner_id = data.winner_id
    match.is_finished = True

    # Определяем ID проигравшего
    loser_id = match.shiro_id if match.aka_id == data.winner_id else match.aka_id

    # 2. Продвигаем ПОБЕДИТЕЛЯ (стандартное дерево)
    if match.next_match_id:
        next_m = await t_db.get(Match, match.next_match_id)
        if match.next_match_position == 1:
            next_m.aka_id = data.winner_id
        else:
            next_m.shiro_id = data.winner_id

        # 3. Продвигаем ПРОИГРАВШЕГО в бой за 3-е место
        # Проверяем: если следующий матч — это ФИНАЛ (у него нет родителя)
        if next_m.next_match_id is None:
            # Ищем созданный при генерации матч за 3-е место (is_repechage=True)
            res_3rd = await t_db.execute(
                select(Match).where(
                    Match.category_id == match.category_id, 
                    Match.is_repechage == True
                )
            )
            third_place = res_3rd.scalar_one_or_none()
            
            if third_place:
                # Если текущий полуфинал был AKA (позиция 1), проигравший станет AKA за 3 место
                if match.next_match_position == 1:
                    third_place.aka_id = loser_id
                else:
                    third_place.shiro_id = loser_id

    await t_db.commit()
    return {"status": "ok", "winner_id": data.winner_id}

# @router.patch("/match/{match_id}")
# async def update_match_score(
#     match_id: int, 
#     data: MatchResultUpdate, 
#     t_db: AsyncSession = Depends(get_t_db)
# ):
#     # 1. Сохраняем результат текущего боя
#     match = await t_db.get(Match, match_id)
#     if not match: 
#         raise HTTPException(status_code=404, detail="Бой не найден")
    
#     match.aka_score = data.aka_score
#     match.shiro_score = data.shiro_score
#     match.winner_id = data.winner_id
#     match.is_finished = True
#     await t_db.commit()

#     # 2. Проверяем все матчи текущего раунда этой категории
#     result = await t_db.execute(
#         select(Match).where(
#             Match.category_id == match.category_id, 
#             Match.round_number == match.round_number
#         )
#     )
#     all_round_matches = result.scalars().all()

#     # Если раунд еще не завершен (есть незаконченные бои) — выходим
#     if not all(m.is_finished for m in all_round_matches):
#         return {"status": "Результат сохранен. Ожидание завершения раунда."}

#     # 3. ПРОВЕРКА НА ФИНАЛ: Нужно ли генерировать следующий круг?
#     # Если в раунде было 2 боя и один из них помечен как бой за 3 место (is_repechage=True)
#     is_final_round = (
#         len(all_round_matches) == 2 and 
#         any(m.is_repechage for m in all_round_matches)
#     )
    
#     # Или если это был единственный бой (финал без боя за 3 место)
#     if is_final_round or len(all_round_matches) == 1:
#         return {"status": "Соревнования в категории завершены. Победители определены."}
# # ... внутри PATCH после сохранения результата ...

#     # 1. Если это круговая система (3 участника в категории)
#     if len(all_round_matches) == 3:
#         # Проверяем, все ли 3 боя завершены
#         if all(m.is_finished for m in all_round_matches):
#             return {"status": "Круговой турнир завершен. Считайте очки для определения мест."}
#         return {"status": "Результат кругового боя сохранен."}


#     # 4. ЛОГИКА ПЕРЕХОДА В СЛЕДУЮЩИЙ КРУГ
#     if len(all_round_matches) == 2:
#         # Если это были полуфиналы (2 боя БЕЗ флага is_repechage)
#         # вызываем создание Финала и Боя за 3 место (как писали ранее)
#         await create_finals_and_third_place(match.category_id, all_round_matches, t_db)
#         return {"status": "Полуфиналы завершены. Созданы финальные бои."}
#     else:
#         # Обычный круг (отборочные)
#         await generate_next_round(match.category_id, match.round_number, t_db)
#         return {"status": "Раунд завершен. Создан следующий круг."}


@router.get("/categories/{category_id}/results")
async def get_results(category_id: int, t_db: AsyncSession = Depends(get_t_db)):
    winners = await get_category_winners(category_id, t_db)
    if winners is None:
        raise HTTPException(status_code=400, detail="Соревнования еще не завершены")
    
    # Для красоты можно подтянуть имена атлетов из основной БД
    return winners

