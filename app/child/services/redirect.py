from collections import defaultdict
from datetime import date

from fastapi.responses import RedirectResponse
from app.child.models.round import Round
from app.child.models.score import Score
from app.child.models.team import Team
from app.child.models.winner import Winner
from sqlalchemy import select, delete, func, or_
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



async def find_eligible_categories(
    athlete: Athlete, 
    categories: list[Category], 
    event_date: date
) -> dict[int, str]:
    """Возвращает список ID ЛИЧНЫХ категорий (только male/female), подходящих атлету."""
    # Возраст по году рождения
    age = event_date.year - athlete.birth_date.year
    eligible_ids = {}
    
    for cat in categories:
         # 1. Проверка пола и возраста (базовый фильтр)
        if cat.gender == athlete.gender and cat.min_age <= age <= cat.max_age:
            
            # 2. Специфика КАТА (обычно только возраст и пол)
            if cat.discipline == "kata":
                eligible_ids[cat.id] = "kata"
                
            # 3. Специфика КУМИТЕ (обязательно проверяем вес)
            elif cat.discipline == "kumite":
                # Если вес не указан, мы не можем гарантировать точность, 
                # но можно добавить в 'подозрительные' или пропустить
                if athlete.weight is not None:
                    min_w = cat.min_weight or 0
                    max_w = cat.max_weight or 999
                    if min_w <= athlete.weight <= max_w:
                        eligible_ids[cat.id] = "kumite"
                        
    return eligible_ids

def get_round_settings(initial_count: int, round_num: int):
    """
    Возвращает: (limit, sort_by_sum, is_final)
    На основе правил турнира.
    """
    if initial_count >= 17:
        if round_num == 1: return 16, False, False
        if round_num == 2: return 8, False, False
        if round_num >= 3: return 8, False, True 
        
    elif initial_count >= 9:
        if round_num == 1: return 8, False, False
        if round_num == 2: return 4, False, False
        if round_num >= 3: return 4, False, True
        
    elif initial_count >= 7:
        if round_num == 1: return 6, False, False
        if round_num == 2: return 4, False, False
        if round_num >= 3: return 4, False, True
        
    elif initial_count == 6:
        if round_num == 1: return 5, False, False
        if round_num == 2: return 4, True, False 
        if round_num >= 3: return 4, True, True   
        
    elif initial_count == 5:
        if round_num == 1: return 5, False, False
        if round_num == 2: return 4, True, False 
        if round_num >= 3: return 4, True, True
        
    elif initial_count == 4:
        if round_num == 1: return 4, False, False
        if round_num == 2: return 3, True, False  # Отбор в финал по сумме 1-2
        if round_num >= 3: return 3, False, True  # ФИНАЛ: только 3-й раунд!
        
    elif initial_count == 3:
        if round_num == 1: return 3, False, False
        if round_num == 2: return 3, False, False 
        if round_num >= 3: return 3, True, True   # Сумма 1-2-3
        
    elif initial_count == 2:
        if round_num == 1: return 2, False, False
        if round_num == 2: return 2, False, False
        if round_num >= 3: return 2, True, True   # Сумма 1-2-3
        
    return 1, False, True


async def get_or_create_round(t_db: AsyncSession, cat_id: int, round_num: float) -> Round:
    """Ищет раунд или создает новый, если его нет. Безопасно работает с float."""
    # Приводим к float, чтобы 3 и 3.0 считались одинаковыми
    target_num = float(round_num) 
    
    res = await t_db.execute(
        select(Round).where(
            Round.category_id == cat_id, 
            Round.round_number == target_num,
            Round.is_tie_break == False # Ищем только основные раунды
        )
    )
    rnd = res.scalar_one_or_none()
    if not rnd:
        rnd = Round(category_id=cat_id, round_number=target_num)
        t_db.add(rnd)
        await t_db.flush() # Обязательно для получения rnd.id
    return rnd


# ==========================================
# ОСНОВНАЯ ФУНКЦИЯ
# ==========================================

async def promote_to_next_round(t_db: AsyncSession, round_id: int):
    # ==========================================
    # ШАГ 1: Инициализация
    # ==========================================
    curr_rnd = await t_db.get(Round, round_id)
    if not curr_rnd or curr_rnd.is_finished:
        return "ALREADY_FINISHED_OR_NOT_FOUND"
    
    cat_id = curr_rnd.category_id
    current_round_num = curr_rnd.round_number

    # Изначальное количество участников
    count_res = await t_db.execute(
        select(func.count(Score.id))
        .join(Round)
        .where(Round.category_id == cat_id, Round.round_number == 1,
               or_(Score.team.has(Team.is_active == True), Score.athlete.has(Athlete.is_active == True)))
    )
    initial_count = count_res.scalar() or 0

    # Участники текущего раунда
    res = await t_db.execute(select(Score).where(Score.round_id == round_id))
    current_perfs = res.scalars().all()
    
    if not current_perfs:
        return "NO_PARTICIPANTS"

    # ==========================================
    # ШАГ 2: Определение режима
    # ==========================================
    is_final = False
    limit = 0
    sort_by_sum = False

    if curr_rnd.is_tie_break:
        limit = curr_rnd.promote_count or 1
        sort_by_sum = False
        # Если это финальный доп. раунд, включаем режим финала
        if getattr(curr_rnd, 'is_final_tie_break', False):
            is_final = True
    else:
        # Применяем матрицу правил
        limit, sort_by_sum, is_final = get_round_settings(initial_count, int(current_round_num))

    # ==========================================
    # ШАГ 3: Подготовка данных и сортировка
    # ==========================================
    participant_data = []
    
    for p in current_perfs:
        # Оценки текущего раунда
        scores = [p.s1 or 0.0, p.s2 or 0.0, p.s3 or 0.0, p.s4 or 0.0, p.s5 or 0.0]
        
        # По умолчанию берем текущий раунд
        val_to_compare = sum(scores)
        min_score_to_compare = min(scores)
        max_score_to_compare = max(scores)

        if sort_by_sum:
            condition = (Score.athlete_id == p.athlete_id) if p.athlete_id else (Score.team_id == p.team_id)
            
            past_scores_res = await t_db.execute(
                select(Score).join(Round)
                .where(Round.category_id == cat_id, condition, Round.round_number <= current_round_num)
            )
            past_scores = past_scores_res.scalars().all()
            
            # 1. Сумма баллов за все раунды
            val_to_compare = sum([sum([s.s1 or 0.0, s.s2 or 0.0, s.s3 or 0.0, s.s4 or 0.0, s.s5 or 0.0]) for s in past_scores])
            
            # 2. Суммы минимальных и максимальных оценок за все раунды
            all_min_scores = []
            all_max_scores = []
            for s in past_scores:
                r_scores = [s.s1 or 0.0, s.s2 or 0.0, s.s3 or 0.0, s.s4 or 0.0, s.s5 or 0.0]
                all_min_scores.append(min(r_scores))
                all_max_scores.append(max(r_scores))
                
            min_score_to_compare = sum(all_min_scores)
            max_score_to_compare = sum(all_max_scores)

        # Ключ сортировки: Сумма -> Мин -> Макс
        sort_key = (val_to_compare, min_score_to_compare, max_score_to_compare)
        
        participant_data.append({
            "a_id": p.athlete_id,
            "t_id": p.team_id,
            "obj": p,
            "sort_key": sort_key,
            "position": p.position
        })

    # Сортируем от лучшего к худшему
    participant_data.sort(key=lambda x: x["sort_key"], reverse=True)

     # ==========================================
    # ШАГ 4: Обработка ФИНАЛА
    # ==========================================
    if is_final:
        is_final_tie_break = getattr(curr_rnd, 'is_final_tie_break', False)
        
        # 1. Если это НЕ тай-брейк, чистим старые результаты
        if not is_final_tie_break:
            await t_db.execute(delete(Winner).where(Winner.category_id == cat_id))
        
        # 2. Если это ФИНАЛЬНЫЙ ТАЙ-БРЕЙК - просто распределяем места и выходим
        if is_final_tie_break:
            # В финальном тай-брейке места определяются просто по порядку в списке.
            # Первые (лучшие) получают свободные места (например, 1 и 2).
            # Мы берем занятые места из базы, чтобы понять, с какого места начинать.
            existing_places_res = await t_db.execute(
                select(Winner.place).where(Winner.category_id == cat_id)
            )
            taken_places = set(existing_places_res.scalars().all())
            
            # Проходим по отсортированному списку и раздаем свободные места
            place_to_assign = 1
            for item in participant_data:
                # Ищем следующее свободное место
                while place_to_assign in taken_places:
                    place_to_assign += 1
                
                item["obj"].place = place_to_assign
                t_db.add(Winner(
                    category_id=cat_id,
                    place=place_to_assign,
                    athlete_id=item["a_id"],
                    team_id=item["t_id"]
                ))
                taken_places.add(place_to_assign)
                place_to_assign += 1
                
            curr_rnd.is_finished = True
            await t_db.commit()
            return "FINAL_TIE_BREAK_COMPLETED"

        # 3. Если это ПЕРВЫЙ ЗАПУСК ФИНАЛА - ищем ничью
        # Сравниваем попарно: если ключ текущего равен ключу следующего - это ничья
        tie_break_list = []
        clear_places = []
        
        i = 0
        while i < len(participant_data):
            # Проверяем, совпадает ли ключ со следующим
            if i + 1 < len(participant_data) and participant_data[i]["sort_key"] == participant_data[i + 1]["sort_key"]:
                # Нашли ничью! Собираем всех, у кого такой же ключ
                current_key = participant_data[i]["sort_key"]
                for j in range(i, len(participant_data)):
                    if participant_data[j]["sort_key"] == current_key:
                        tie_break_list.append(participant_data[j])
                    else:
                        break # Ключи кончились, ничья закончилась
                
                # Запоминаем, с какого индекса началась ничья, чтобы потом 
                # записать тех, кто идет после
                tie_start_index = i
                break # Дальше искать не нужно, обычно ничья только на границе призов
            else:
                # Ничьей нет - место определено
                participant_data[i]["obj"].place = i + 1
                clear_places.append(participant_data[i])
                i += 1

        # Если ничья найдена
        if tie_break_list:
            # Записываем в Winner тех, кто не попал в ничью
            for item in clear_places:
                t_db.add(Winner(
                    category_id=cat_id,
                    place=item["obj"].place,
                    athlete_id=item["a_id"],
                    team_id=item["t_id"]
                ))
            
            # Записываем тех, кто идет ПОСЛЕ ничьей (например, 3-е место при споре за 1-2)
            for k in range(tie_start_index + len(tie_break_list), len(participant_data)):
                item = participant_data[k]
                item["obj"].place = k + 1
                t_db.add(Winner(
                    category_id=cat_id,
                    place=item["obj"].place,
                    athlete_id=item["a_id"],
                    team_id=item["t_id"]
                ))

            # Создаем доп. раунд
            tie_rnd = Round(
                category_id=cat_id, 
                round_number=current_round_num + 0.1, 
                is_tie_break=True, 
                is_final_tie_break=True, 
                parent_round_id=curr_rnd.id,
                promote_count=len(tie_break_list) 
            )
            t_db.add(tie_rnd)
            await t_db.flush()
            
            for item in tie_break_list:
                t_db.add(Score(
                    round_id=tie_rnd.id, 
                    athlete_id=item["a_id"], 
                    team_id=item["t_id"], 
                    position=item["position"]
                ))
                
            curr_rnd.is_finished = True
            await t_db.commit()
            return "FINAL_TIE_BREAK_CREATED"

        # Если ничьей нет - просто записываем всех
        for index, item in enumerate(participant_data):
            place = index + 1
            item["obj"].place = place 
            t_db.add(Winner(
                category_id=cat_id,
                place=place,
                athlete_id=item["a_id"],
                team_id=item["t_id"]
            ))
        
        curr_rnd.is_finished = True
        await t_db.commit()
        return "FINAL_COMPLETED"

    # ==========================================
    # ШАГ 5: Логика перехода (для обычных и нефинальных доп. раундов)
    # ==========================================
    if curr_rnd.is_tie_break:
        # --- ВЫХОД ИЗ ДОП. РАУНДА ---
        parent_rnd = await t_db.get(Round, curr_rnd.parent_round_id)
        
        # ЖЕСТКО берем номер родительского + 1, игнорируя номер текущего (2.1)
        next_round_num = float(int(parent_rnd.round_number) + 1)
        
        next_rnd = await get_or_create_round(t_db, cat_id, next_round_num)
        
        promoted = participant_data[:limit]
        
        # Защита от дублей
        ex_res = await t_db.execute(select(Score).where(Score.round_id == next_rnd.id))
        existing = ex_res.scalars().all()
        existing_keys = {(s.athlete_id, s.team_id) for s in existing}

        for item in promoted:
            key = (item["a_id"], item["t_id"])
            if key not in existing_keys:
                t_db.add(Score(
                    round_id=next_rnd.id, 
                    athlete_id=item["a_id"], 
                    team_id=item["t_id"], 
                    position=item["position"]
                ))
        
        curr_rnd.is_finished = True
        await t_db.commit()
        return f"TIE_BREAK_RESOLVED_PROMOTED_{len(promoted)}"

    else:
        # --- ОБЫЧНЫЙ ПЕРЕХОД ---
        next_round_num = float(int(current_round_num) + 1)
        
        # Проверка: нужен ли тай-брейк?
        if 0 < limit < len(participant_data):
            border_key = participant_data[limit - 1]["sort_key"]
            next_key = participant_data[limit]["sort_key"]
            
            if border_key == next_key:
                tie_break_list = [i for i in participant_data if i["sort_key"] == border_key]
                clear_pass_list = [i for i in participant_data if i["sort_key"] > border_key]
                
                places_to_play_for = limit - len(clear_pass_list)

                tie_rnd = Round(
                    category_id=cat_id, 
                    round_number=current_round_num + 0.1, 
                    is_tie_break=True, 
                    parent_round_id=curr_rnd.id,
                    promote_count=places_to_play_for
                )
                t_db.add(tie_rnd)
                await t_db.flush() 
                
                for item in tie_break_list:
                    t_db.add(Score(round_id=tie_rnd.id, athlete_id=item["a_id"], team_id=item["t_id"], position=item["position"]))
                
                next_rnd = await get_or_create_round(t_db, cat_id, next_round_num)
                for item in clear_pass_list:
                    t_db.add(Score(round_id=next_rnd.id, athlete_id=item["a_id"], team_id=item["t_id"], position=item["position"]))
                
                curr_rnd.is_finished = True
                await t_db.commit()
                return "TIE_BREAK_CREATED"

        # Если тай-брейк не нужен, просто переводим лучших
        if limit > 0:
            next_rnd = await get_or_create_round(t_db, cat_id, next_round_num)
            promoted = participant_data[:limit]
            
            ex_res = await t_db.execute(select(Score).where(Score.round_id == next_rnd.id))
            existing = ex_res.scalars().all()
            existing_keys = {(s.athlete_id, s.team_id) for s in existing}

            for item in promoted:
                key = (item["a_id"], item["t_id"])
                if key not in existing_keys:
                    t_db.add(Score(
                        round_id=next_rnd.id, 
                        athlete_id=item["a_id"], 
                        team_id=item["t_id"], 
                        position=item["position"]
                    ))
            
            curr_rnd.is_finished = True
            await t_db.commit()
            return f"PROMOTED_{limit}_PARTICIPANTS"

    return "NO_ACTION"


# async def promote_to_next_round(t_db: AsyncSession, round_id: int):
#     curr_rnd = await t_db.get(Round, round_id)
#     cat_id = curr_rnd.category_id
#     current_round_num = curr_rnd.round_number

    
#     # 1. Получаем изначальное количество участников
#     count_res = await t_db.execute(
#         select(func.count(Score.id)).join(Round).where(Round.category_id == cat_id, Round.round_number == 1)
#     )
#     initial_count = count_res.scalar() or 0

#     res = await t_db.execute(select(Score).where(Score.round_id == round_id))
#     current_perfs = res.scalars().all()
#     original_order = [p.id for p in current_perfs]

#     # 2. Определяем режим: Финал, Лимит прохода, Способ сортировки
#     is_final = False
#     limit = 0
#     sort_by_sum = False
    
#     if initial_count <= 3:
#         limit = initial_count
#         if current_round_num >= 3: is_final, sort_by_sum = True, True
#     elif initial_count == 4:
#         if current_round_num == 1: limit = 4
#         elif current_round_num == 2: limit, sort_by_sum = 3, True
#         elif current_round_num == 3: is_final, sort_by_sum = True, False
#     else:
#         # Если это доп. раунд, лимит — это количество спорных мест (обычно определяется по parent)
#         if curr_rnd.is_tie_break:
#             limit = 1 # В переигровке обычно ищем одного лучшего на вакантное место
#         else:
#             limit = get_promotion_count(initial_count, current_round_num)
        
#         if current_round_num >= 3 and not curr_rnd.is_tie_break:
#             is_final = True

#     # 3. Подготовка данных с Ключом Тай-брейка
#     participant_data = []
#     for p in current_perfs:
#         scores = [p.s1 or 0.0, p.s2 or 0.0, p.s3 or 0.0, p.s4 or 0.0, p.s5 or 0.0]
#         # Сортировка WKF: Балл -> Мин отброшенная -> Макс отброшенная
#         sort_key = (p.total_score or 0.0, min(scores), max(scores))
        
#         val_to_compare = p.total_score or 0.0
#         if sort_by_sum:
#             condition = (Score.athlete_id == p.athlete_id) if p.athlete_id else (Score.team_id == p.team_id)
#             sum_res = await t_db.execute(
#                 select(func.sum(Score.total_score)).join(Round)
#                 .where(Round.category_id == cat_id, condition, Round.round_number <= current_round_num)
#             )
#             val_to_compare = sum_res.scalar() or 0.0

#         sort_key = (val_to_compare, min(scores), max(scores))
        
#         participant_data.append({
#             "a_id": p.athlete_id, 
#             "t_id": p.team_id, 
#             "obj": p, 
#             "sort_key": sort_key,
#             "position": p.position
#         })

#     participant_data.sort(key=lambda x: x["sort_key"], reverse=True)

#     # 4. ПРОВЕРКА НА ТАЙ-БРЕЙК
#     tie_break_list = []
#     clear_pass_list = []

#     if not is_final and 0 < limit < len(participant_data):
#         border_key = participant_data[limit - 1]["sort_key"]
#         next_key = participant_data[limit]["sort_key"]
        
#         if border_key == next_key:
#             tie_break_list = [i for i in participant_data if i["sort_key"] == border_key]
#             clear_pass_list = [i for i in participant_data if i["sort_key"] > border_key]

#     if tie_break_list:
#         # Создаем доп. раунд
#         tie_rnd = Round(category_id=cat_id, round_number=current_round_num + 0.1, is_tie_break=True, parent_round_id=curr_rnd.id)
#         t_db.add(tie_rnd)
        
#         # Основной следующий раунд
#         next_num = int(current_round_num) + 1
#         next_rnd = Round(category_id=cat_id, round_number=next_num)
#         t_db.add(next_rnd)
#         await t_db.flush()

#         # Заполняем спорщиками (важно: передаем и athlete_id, и team_id)
#         for item in tie_break_list:
#             t_db.add(Score(round_id=tie_rnd.id, athlete_id=item["a_id"], team_id=item["t_id"], position = item["position"]))
            
#         # Заполняем следующий раунд лидерами
#         for item in clear_pass_list:
#             t_db.add(Score(round_id=next_rnd.id, athlete_id=item["a_id"], team_id=item["t_id"], position = item["position"]))
        
#         curr_rnd.is_finished = True
#         await t_db.commit()
#         return "TIE_BREAK_CREATED"

#     # 5. ФИНАЛ: Записываем места
#     if is_final:
#         # Очищаем старых победителей категории (если есть)
#         await t_db.execute(delete(Winner).where(Winner.category_id == cat_id))
#         for index, item in enumerate(participant_data):
#             place = index + 1
#             item["obj"].place = place
#             # Если у вас есть таблица Winner, добавьте логику туда аналогично Score
#             new_winner = Winner(
#                 category_id=cat_id,
#                 place=place,
#                 athlete_id=item["a_id"],  # Будет None, если это команда
#                 team_id=item["t_id"],     # Будет None, если это личник
#             )
#             t_db.add(new_winner)

#     # 6. ОБЫЧНЫЙ ПЕРЕХОД
#     elif limit > 0:
#         if curr_rnd.is_tie_break:
#             parent_rnd = await t_db.get(Round, curr_rnd.parent_round_id)
#             next_num = int(parent_rnd.round_number) + 1
#         else:
#             next_num = int(current_round_num) + 1

#         nr_res = await t_db.execute(select(Round).where(Round.category_id == cat_id, Round.round_number == next_num))
#         next_rnd = nr_res.scalar_one_or_none() or Round(category_id=cat_id, round_number=next_num)
#         if not next_rnd.id: t_db.add(next_rnd)
#         await t_db.flush()

#         # Получаем ID тех, кто уже в следующем раунде, чтобы избежать дублей
#         ex_res = await t_db.execute(select(Score).where(Score.round_id == next_rnd.id))
#         existing = ex_res.scalars().all()
#         existing_keys = {(s.athlete_id, s.team_id) for s in existing}

#         promoted = participant_data[:limit]
#         promoted.sort(key=lambda x: original_order.index(x["obj"].id))
#         for item in promoted:
#             key = (item["a_id"], item["t_id"])
#             if key not in existing_keys:
#                 t_db.add(Score(round_id=next_rnd.id, athlete_id=item["a_id"], team_id=item["t_id"]))

#     curr_rnd.is_finished = True
#     await t_db.commit()
#     return limit