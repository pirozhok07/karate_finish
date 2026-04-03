from collections import defaultdict
from datetime import date
from app.child.models.round import Round
from app.child.models.score import Score
from app.child.models.team import Team
from app.child.models.winner import Winner
from sqlalchemy import select, delete, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.child.models.draft import DraftAssignment
from app.child.models.category import Category 
from app.child.models.athlete import Athlete
from app.tournament_main.model import Tournament
from app.child.services.logic import find_category_id, get_athlete_age, get_promotion_count, get_wkf_sort_key

# async def run_draft_assignment_logic(tournament_id: int, main_db: AsyncSession, t_db: AsyncSession): старая
#     """Общая логика расчета черновика распределения."""
#     # 1. Очистка старого черновика
#     await t_db.execute(delete(DraftAssignment))

#     # 2. Получение данных
#     tournament = await main_db.get(Tournament, tournament_id)
#     categories = (await t_db.execute(select(Category))).scalars().all()
#     athletes = (await t_db.execute(select(Athlete))).scalars().all()

#     # 3. Распределение
#     for auth in athletes:
#         cat_id = find_category_id(auth, categories, tournament.event_date)
        
#         draft = DraftAssignment(
#             athlete_id=auth.id,
#             category_id=cat_id,
#             reason="Автоматическое распределение" if cat_id else "Категория не найдена"
#         )
#         t_db.add(draft)

#     await t_db.commit()
#     return len(athletes)

async def run_draft_assignment_logic(tournament_id: int, main_db: AsyncSession, t_db: AsyncSession):
# 1. Очистка старого черновика
    await t_db.execute(delete(DraftAssignment))

    tournament = await main_db.get(Tournament, tournament_id)
    categories = (await t_db.execute(select(Category))).scalars().all()
    
    # Загружаем всех атлетов и все команды с участниками
    athletes = (await t_db.execute(select(Athlete))).scalars().all()
    teams_res = await t_db.execute(select(Team).options(selectinload(Team.members)))
    teams = teams_res.scalars().all()

    # 1. Распределяем ЛИЧНИКОВ (только в гендерные категории)
    for athlete in athletes:
        # ВАЖНО: Проверяем, заявлялся ли он в личку (флаг из импорта)
        # Если флага нет в модели, можно убрать это условие или добавить поле в БД
        if getattr(athlete, 'is_personal', True): 
            personal_cats = [c for c in categories if c.gender in ["male", "female"]]
            category_ids = await find_eligible_categories(athlete, personal_cats, tournament.event_date)
            
            for cat_id in category_ids:
                t_db.add(DraftAssignment(
                    athlete_id=athlete.id, 
                    category_id=cat_id,
                    reason="Личное распределение (авто)"
                ))

    # 2. Распределяем КОМАНДЫ
    for team in teams:
        # Команды ищем только в категориях unisex (или командных ката)
        team_cats = [c for c in categories if c.gender == "unisex"]
        
        for cat in team_cats:
            if not team.members:
                continue
                
            # Проверка возраста для ВСЕХ участников группы по году рождения
            # (Все должны попадать в диапазон категории)
            ages = [tournament.event_date.year - m.birth_date.year for m in team.members]
            
            if all(cat.min_age <= age <= cat.max_age for age in ages):
                t_db.add(DraftAssignment(
                    team_id=team.id,
                    category_id=cat.id,
                    reason=f"Командное распределение ({cat.name})"
                ))

    await t_db.commit()

async def find_eligible_categories(
    athlete: Athlete, 
    categories: list[Category], 
    event_date: date
) -> list[int]:
    """Возвращает список ID ЛИЧНЫХ категорий (только male/female), подходящих атлету."""
    # Возраст по году рождения
    age = event_date.year - athlete.birth_date.year
    eligible_ids = []
    
    for cat in categories:
         # 1. Проверка пола и возраста (базовый фильтр)
        if cat.gender == athlete.gender and cat.min_age <= age <= cat.max_age:
            
            # 2. Специфика КАТА (обычно только возраст и пол)
            if cat.discipline == "kata":
                eligible_ids.append(cat.id)
                
            # 3. Специфика КУМИТЕ (обязательно проверяем вес)
            elif cat.discipline == "kumite":
                # Если вес не указан, мы не можем гарантировать точность, 
                # но можно добавить в 'подозрительные' или пропустить
                if athlete.weight is not None:
                    min_w = cat.min_weight or 0
                    max_w = cat.max_weight or 999
                    if min_w <= athlete.weight <= max_w:
                        eligible_ids.append(cat.id)
                        
    return eligible_ids

async def promote_to_next_round(t_db: AsyncSession, round_id: int):
    curr_rnd = await t_db.get(Round, round_id)
    cat_id = curr_rnd.category_id
    current_round_num = curr_rnd.round_number

    # 1. Получаем изначальное количество участников
    count_res = await t_db.execute(
        select(func.count(Score.id)).join(Round).where(Round.category_id == cat_id, Round.round_number == 1)
    )
    initial_count = count_res.scalar() or 0

    res = await t_db.execute(select(Score).where(Score.round_id == round_id))
    current_perfs = res.scalars().all()

    # 2. Определяем режим: Финал, Лимит прохода, Способ сортировки
    is_final = False
    limit = 0
    sort_by_sum = False
    
    if initial_count <= 3:
        limit = initial_count
        if current_round_num >= 3: is_final, sort_by_sum = True, True
    elif initial_count == 4:
        if current_round_num == 1: limit = 4
        elif current_round_num == 2: limit, sort_by_sum = 3, True
        elif current_round_num == 3: is_final, sort_by_sum = True, False
    else:
        # Если это доп. раунд, лимит — это количество спорных мест (обычно определяется по parent)
        if curr_rnd.is_tie_break:
            limit = 1 # В переигровке обычно ищем одного лучшего на вакантное место
        else:
            limit = get_promotion_count(initial_count, current_round_num)
        
        if current_round_num >= 3 and not curr_rnd.is_tie_break:
            is_final = True

    # 3. Подготовка данных с Ключом Тай-брейка
    participant_data = []
    for p in current_perfs:
        scores = [p.s1 or 0.0, p.s2 or 0.0, p.s3 or 0.0, p.s4 or 0.0, p.s5 or 0.0]
        # Сортировка WKF: Балл -> Мин отброшенная -> Макс отброшенная
        sort_key = (p.total_score or 0.0, min(scores), max(scores))
        
        val_to_compare = p.total_score or 0.0
        if sort_by_sum:
            condition = (Score.athlete_id == p.athlete_id) if p.athlete_id else (Score.team_id == p.team_id)
            sum_res = await t_db.execute(
                select(func.sum(Score.total_score)).join(Round)
                .where(Round.category_id == cat_id, condition, Round.round_number <= current_round_num)
            )
            val_to_compare = sum_res.scalar() or 0.0

        sort_key = (val_to_compare, min(scores), max(scores))
        
        participant_data.append({
            "a_id": p.athlete_id, 
            "t_id": p.team_id, 
            "obj": p, 
            "sort_key": sort_key
        })

    participant_data.sort(key=lambda x: x["sort_key"], reverse=True)

    # 4. ПРОВЕРКА НА ТАЙ-БРЕЙК
    tie_break_list = []
    clear_pass_list = []

    if not is_final and 0 < limit < len(participant_data):
        border_key = participant_data[limit - 1]["sort_key"]
        next_key = participant_data[limit]["sort_key"]
        
        if border_key == next_key:
            tie_break_list = [i for i in participant_data if i["sort_key"] == border_key]
            clear_pass_list = [i for i in participant_data if i["sort_key"] > border_key]

    if tie_break_list:
        # Создаем доп. раунд
        tie_rnd = Round(category_id=cat_id, round_number=current_round_num + 0.1, is_tie_break=True, parent_round_id=curr_rnd.id)
        t_db.add(tie_rnd)
        
        # Основной следующий раунд
        next_num = int(current_round_num) + 1
        next_rnd = Round(category_id=cat_id, round_number=next_num)
        t_db.add(next_rnd)
        await t_db.flush()

        # Заполняем спорщиками (важно: передаем и athlete_id, и team_id)
        for item in tie_break_list:
            t_db.add(Score(round_id=tie_rnd.id, athlete_id=item["a_id"], team_id=item["t_id"]))
            
        # Заполняем следующий раунд лидерами
        for item in clear_pass_list:
            t_db.add(Score(round_id=next_rnd.id, athlete_id=item["a_id"], team_id=item["t_id"]))
        
        curr_rnd.is_finished = True
        await t_db.commit()
        return "TIE_BREAK_CREATED"

    # 5. ФИНАЛ: Записываем места
    if is_final:
        # Очищаем старых победителей категории (если есть)
        await t_db.execute(delete(Winner).where(Winner.category_id == cat_id))
        for index, item in enumerate(participant_data):
            place = index + 1
            item["obj"].place = place
            # Если у вас есть таблица Winner, добавьте логику туда аналогично Score
            new_winner = Winner(
                category_id=cat_id,
                place=place,
                athlete_id=item["a_id"],  # Будет None, если это команда
                team_id=item["t_id"],     # Будет None, если это личник
            )
            t_db.add(new_winner)

    # 6. ОБЫЧНЫЙ ПЕРЕХОД
    elif limit > 0:
        if curr_rnd.is_tie_break:
            parent_rnd = await t_db.get(Round, curr_rnd.parent_round_id)
            next_num = int(parent_rnd.round_number) + 1
        else:
            next_num = int(current_round_num) + 1

        nr_res = await t_db.execute(select(Round).where(Round.category_id == cat_id, Round.round_number == next_num))
        next_rnd = nr_res.scalar_one_or_none() or Round(category_id=cat_id, round_number=next_num)
        if not next_rnd.id: t_db.add(next_rnd)
        await t_db.flush()

        # Получаем ID тех, кто уже в следующем раунде, чтобы избежать дублей
        ex_res = await t_db.execute(select(Score).where(Score.round_id == next_rnd.id))
        existing = ex_res.scalars().all()
        existing_keys = {(s.athlete_id, s.team_id) for s in existing}

        promoted = participant_data[:limit]
        for item in promoted:
            key = (item["a_id"], item["t_id"])
            if key not in existing_keys:
                t_db.add(Score(round_id=next_rnd.id, athlete_id=item["a_id"], team_id=item["t_id"]))

    curr_rnd.is_finished = True
    await t_db.commit()
    return limit