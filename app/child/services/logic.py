from datetime import date
from app.child.models.athlete import Athlete
from app.child.models.category import Category
from app.child.models.round import Round
from app.child.models.score import Score
from app.child.models.team import Team
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, delete

def get_athlete_age(birth_date: date, event_date: date) -> int:
    """Вычисляет количество полных лет на момент турнира."""
    return event_date.year - birth_date.year - (
        (event_date.month, event_date.day) < (birth_date.month, birth_date.day)
    )

def find_category_id(
    participant: Athlete | Team, 
    categories: list[Category], 
    event_date: date,
) -> int | None:
    """Универсальный поиск: для атлетов (личка) и команд (unisex)."""
    
    # 1. Определяем параметры участника (пол и возраст)
    
    gender_to_find = participant.gender
    age = get_athlete_age(participant.birth_date, event_date)
    
    # 2. Ищем подходящую категорию в списке
    for cat in categories:
        # Проверяем дисциплину (если нужно, можно добавить в аргументы, например "kata")
        if (cat.gender == gender_to_find and 
            cat.min_age <= age <= cat.max_age):
            return cat.id
            
    return None

def get_promotion_count(current_count: int, round_number: int) -> int:
    """
    Определяет количество выходящих в следующий круг по сетке.
    Логика: (1 круг : 2 круг : 3 круг) 
    """
    if round_number == 1:
        if current_count >= 17: return 16
        if current_count >= 9: return 8
        if current_count >= 7: return 6 # для 8:6:4 берем 6
        if current_count == 6: return 5 # для 8:6:4 берем 6
        if current_count >= 4: return 4
        return current_count # 3:3, 2:2
    
    if round_number == 2:
        if current_count >= 16: return 8
        if current_count >= 5: return 4
        if current_count >= 3: return 3
        return current_count
    
    return current_count

# def sort_performances_wkf(performances):
#     """
#     Сортировка по правилам WKF:
#     1. Итоговый балл (DESC)
#     2. Низшая из отброшенных (DESC) - т.е. самая высокая из плохих
#     3. Высшая из отброшенных (DESC)
#     """
#     def get_key(p):
#         scores = sorted([p.s1, p.s2, p.s3, p.s4, p.s5])
#         # Отброшенные это scores[0] (min) и scores[-1] (max)
#         # 1. total_score
#         # 2. scores[0] (самая низкая из всех)
#         # 3. scores[-1] (самая высокая из всех)
#         return (p.total_score, scores[0], scores[-1])

#     return sorted(performances, key=get_key, reverse=True)

def get_wkf_sort_key(p):
    """Ключ для разрешения ничьих: Балл -> Худшая оценка -> Лучшая оценка"""
    all_scores = sorted([p.s1, p.s2, p.s3, p.s4, p.s5])
    return (p.total_score, all_scores[0], all_scores[-1])

# async def promote_to_next_round(t_db: AsyncSession, round_id: int):
#     """Логика перехода между кругами и записи мест в финале"""
#     # 1. Загружаем текущий круг и всех участников в нем
#     curr_rnd = await t_db.get(Round, round_id)
#     res = await t_db.execute(select(Score).where(Score.round_id == round_id))
#     perfs = res.scalars().all()

#     if not perfs:
#         return 0

#     # 2. Сортируем по правилам WKF (от лучшего к худшему)
#     sorted_p = sorted(perfs, key=get_wkf_sort_key, reverse=True)
    
#     # 3. Определяем, сколько человек должно пройти дальше
#     limit = get_promotion_count(len(perfs), curr_rnd.round_number)
    
#     # 4. Проверяем, является ли этот круг ФИНАЛЬНЫМ
#     # Финал если: это 3-й круг ИЛИ участников настолько мало, что дальше делить некуда
#     is_final = curr_rnd.round_number == 3 or limit == len(perfs)
    
#     if is_final:
#         print(is_final)
#         # ЗАПИСЫВАЕМ МЕСТА В БАЗУ (только для финала)
#         for index, p in enumerate(sorted_p):
#             p.place = index + 1
#     else:
#         print(f"СОЗДАЕМ СЛЕДУЮЩИЙ КРУГ")
#         # СОЗДАЕМ СЛЕДУЮЩИЙ КРУГ
#         next_rnd = Round(
#             category_id=curr_rnd.category_id, 
#             round_number=curr_rnd.round_number + 1
#         )
#         t_db.add(next_rnd)
#         await t_db.flush() # Получаем ID нового круга

#         # ПЕРЕНОСИМ ЛУЧШИХ (сохраняя либо athlete_id, либо team_id)
#         for p in sorted_p[:limit]:
#             print(p)
#             new_score = Score(
#                 round_id=next_rnd.id,
#                 athlete_id=p.athlete_id, # Если это личник, перенесется ID
#                 team_id=p.team_id        # Если это команда, перенесется ID
#             )
#             t_db.add(new_score)
#             print(f"Переход: Round {next_rnd.round_number}, Athlete: {p.athlete_id}, Team: {p.team_id}")
#     # Помечаем круг как завершенный
#     curr_rnd.is_finished = True
    
#     # Сохраняем всё одним махом
#     await t_db.commit()
#     return limit

async def sync_team_presence(t_db: AsyncSession, athlete_id: int):
    # 1. Находим все команды, где участвует этот атлет
    # Используем join или связь, если она настроена
    result = await t_db.execute(
        select(Team)
        .join(Team.members)
        .where(Athlete.id == athlete_id)
        .options(selectinload(Team.members)) # Подгружаем состав сразу
    )
    teams = result.scalars().all()
    
    updated_teams = []
    
    for team in teams:
        # 2. Проверяем: все ли члены этой конкретной команды "явились"
        # Если хотя бы один False — команда "не явилась"
        all_present = all(m.is_present for m in team.members)
        
        # 3. Если статус изменился — обновляем в базе
        if team.is_present != all_present:
            team.is_present = all_present
            updated_teams.append(team)
            
    # Мы не делаем commit тут, его сделает основная функция update_athlete
    return updated_teams