from datetime import date
import math
from operator import and_, or_
import random
from app.child.models.athlete import Athlete
from app.child.models.category import Category
from app.child.models.draft import DraftAssignment
from app.child.models.match import Match
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

import random
import math

import math

async def generate_kumite_bracket(category_id: int, t_db: AsyncSession):
    result = await t_db.execute(select(DraftAssignment).where(DraftAssignment.category_id == category_id))
    athlete_ids = [a.athlete_id for a in result.scalars().all()]
    n = len(athlete_ids)
    
    if n < 2: return "Мало участников"

    # --- КРУГОВАЯ СИСТЕМА ДЛЯ 3 УЧАСТНИКОВ ---
    if n == 3:
        p1, p2, p3 = athlete_ids
        # Генерируем 3 матча: 1vs2, 2vs3, 3vs1
        pairs = [(p1, p2), (p2, p3), (p3, p1)]
        
        for idx, (aka, shiro) in enumerate(pairs, 1):
            match = Match(
                category_id=category_id,
                aka_id=aka,
                shiro_id=shiro,
                round_number=1, # В круговой системе всё в одном раунде
                number=idx,
                is_repechage=True # Пометим как "круговой", чтобы PATCH не создавал финал
            )
            t_db.add(match)
        await t_db.commit()
        return {"status": "Создана круговая сетка для 3 участников"}

    # --- ОЛИМПИЙСКАЯ СИСТЕМА (для 2, 4, 5+ участников) ---

    # Находим ближайшую степень двойки "снизу" (для 5 это 4, для 11 это 8)
    next_pow2 = 2**int(math.log2(n))
    # Сколько человек должны подраться в 1-м раунде, чтобы осталось ровно next_pow2
    num_qualifying_fights = n - next_pow2 
    num_athletes_in_fights = num_qualifying_fights * 2

    import random
    random.shuffle(athlete_ids)

    # 1. Те, кто дерутся в Раунде 1
    fighers_r1 = athlete_ids[:num_athletes_in_fights]
    # 2. Те, кто сразу проходят в Раунд 2 (ждут)
    waiters_r2 = athlete_ids[num_athletes_in_fights:]

    match_counter = 1
    # Создаем реальные бои Раунда 1
    for i in range(0, len(fighers_r1), 2):
        match = Match(
            category_id=category_id,
            aka_id=fighers_r1[i],
            shiro_id=fighers_r1[i+1],
            round_number=1,
            number=match_counter
        )
        t_db.add(match)
        match_counter += 1

    # ВАЖНО: Нам нужно где-то сохранить "ждущих" атлетов, 
    # чтобы generate_next_round их увидел. 
    # Создадим для них "технические" матчи в Раунде 1, которые уже завершены.
    for athlete_id in waiters_r2:
        match = Match(
            category_id=category_id,
            aka_id=athlete_id,
            shiro_id=None,
            round_number=1,
            number=match_counter,
            is_finished=True,
            winner_id=athlete_id
        )
        t_db.add(match)
        match_counter += 1

    await t_db.commit()



async def generate_next_round(category_id: int, current_round: int, t_db: AsyncSession):
    # 1. Берем всех победителей завершенного раунда
    result = await t_db.execute(
        select(Match)
        .where(Match.category_id == category_id, Match.round_number == current_round)
        .order_by(Match.number)
    )
    finished_matches = result.scalars().all()
    
    if any(not m.is_finished for m in finished_matches):
        return {"error": "Не все бои завершены"}

    # Победители текущего круга
    winners = [m.winner_id for m in finished_matches if m.winner_id is not None]

    # ВАЖНО: Если у нас были люди, которые "ждали" в этом раунде, 
    # они должны быть добавлены к списку победителей для следующего круга.
    # Но в правильной сетке "ждущие" тоже должны быть оформлены как Match с одним участником.

    if len(winners) <= 1:
        return {"message": "Победитель определен"}

    next_round = current_round + 1
    match_counter = 1
    
    # Формируем пары строго по порядку
    for i in range(0, len(winners), 2):
        aka_id = winners[i]
        shiro_id = winners[i+1] if i + 1 < len(winners) else None
        
        # Если shiro_id нет, участник снова проходит дальше автоматически
        auto_win = shiro_id is None
        
        new_match = Match(
            category_id=category_id,
            aka_id=aka_id,
            shiro_id=shiro_id,
            round_number=next_round,
            number=match_counter,
            is_finished=auto_win,
            winner_id=aka_id if auto_win else None
        )
        t_db.add(new_match)
        match_counter += 1
    
    await t_db.commit()


async def get_path_to_final(winner_id: int, category_id: int, t_db: AsyncSession):
    """Возвращает список ID атлетов, проигравших финалисту (winner_id)."""
    result = await t_db.execute(
        select(Match)
        .where(Match.category_id == category_id)
        .where((Match.aka_id == winner_id) | (Match.shiro_id == winner_id))
        .where(Match.winner_id == winner_id)
        .order_by(Match.round_number)
    )
    matches = result.scalars().all()
    
    losers = []
    for m in matches:
        loser_id = m.shiro_id if m.aka_id == winner_id else m.aka_id
        if loser_id:
            losers.append(loser_id)
    return losers

async def generate_repechage(category_id: int, finalist_id: int, side_name: str, t_db: AsyncSession):
    """Создает лестницу утешительных боев для одной стороны (пул А или Б)."""
    losers = await get_path_to_final(finalist_id, category_id, t_db)
    
    if len(losers) < 2:
        return # Некого утешать

    # В утешении первый проигравший дерется со вторым, 
    # победитель — с третьим и т.д. за бронзу.
    current_aka = losers[0]
    for i in range(1, len(losers)):
        new_match = Match(
            category_id=category_id,
            aka_id=current_aka,
            shiro_id=losers[i],
            round_number=99, # Условный номер для утешения
            is_repechage=True,
            number=i
        )
        t_db.add(new_match)
        # В каратэ утешение идет по цепочке, но для Swagger 
        # проще создать первый бой, а остальные — после ввода результата.
        break 

    await t_db.commit()

async def create_finals_and_third_place(category_id: int, semi_final_matches: list[Match], t_db: AsyncSession):
    """
    Принимает два матча полуфинала, находит победителей и проигравших,
    и создает финальный и малый финальный (за 3-е место) бои.
    """
    winners = []
    losers = []

    for m in semi_final_matches:
        winners.append(m.winner_id)
        # Проигравший — это тот, кто НЕ winner_id
        loser_id = m.shiro_id if m.aka_id == m.winner_id else m.aka_id
        if loser_id: # Добавляем, только если это не был технический бой (автопобеда)
            losers.append(loser_id)

    next_round = semi_final_matches[0].round_number + 1

    # 1. Создаем ФИНАЛ (1-2 место)
    final_match = Match(
        category_id=category_id,
        aka_id=winners[0],
        shiro_id=winners[1] if len(winners) > 1 else None,
        round_number=next_round,
        number=1,
        is_repechage=False # Это финал
    )
    t_db.add(final_match)

    # 2. Создаем БОЙ ЗА 3-Е МЕСТО (только если есть два проигравших)
    if len(losers) == 2:
        third_place_match = Match(
            category_id=category_id,
            aka_id=losers[0],
            shiro_id=losers[1],
            round_number=next_round,
            number=2,
            is_repechage=True # Помечаем как технический флаг для боя за 3-е место
        )
        t_db.add(third_place_match)
    
    await t_db.commit()


async def get_category_winners(category_id: int, t_db: AsyncSession):
    # Получаем все матчи категории
    result = await t_db.execute(
        select(Match).where(Match.category_id == category_id)
    )
    matches = result.scalars().all()
    
    if not all(m.is_finished for m in matches):
        return None # Еще не все бои сыграны

    # ОПРЕДЕЛЕНИЕ СИСТЕМЫ
    # Если матчей 3 и у них одинаковый round_number — это круговая система
    if len(matches) == 3 and all(m.round_number == 1 for m in matches):
        return await calculate_round_robin(matches, t_db)
    
    # Иначе — ОЛИМПИЙСКАЯ СИСТЕМА
    return await calculate_olympic(matches, t_db)

async def calculate_olympic(matches, t_db):
    # 1. Находим Финал (у него нет next_match_id и is_repechage == False)
    final = next((m for m in matches if m.next_match_id is None and not m.is_repechage), None)
    
    # 2. Находим Бой за 3 место (is_repechage == True)
    third_place_match = next((m for m in matches if m.is_repechage), None)

    if not final or not final.is_finished:
        return None # Категория еще не завершена

    results = []
    
    # 1 место — победитель финала
    results.append({"place": 1, "athlete_id": final.winner_id})
    
    # 2 место — проигравший в финале
    silver_id = final.shiro_id if final.winner_id == final.aka_id else final.aka_id
    if silver_id:
        results.append({"place": 2, "athlete_id": silver_id})
    
    # 3 место — победитель малого финала
    if third_place_match and third_place_match.is_finished and third_place_match.winner_id:
        results.append({"place": 3, "athlete_id": third_place_match.winner_id})
    
    return results

async def calculate_round_robin(matches, t_db):
    stats = {} # {athlete_id: {"wins": 0, "points": 0}}
    
    for m in matches:
        for p_id in [m.aka_id, m.shiro_id]:
            if p_id not in stats: stats[p_id] = {"wins": 0, "points": 0}
        
        # Добавляем баллы
        stats[m.aka_id]["points"] += m.aka_score
        stats[m.shiro_id]["points"] += m.shiro_score
        # Добавляем победу
        if m.winner_id:
            stats[m.winner_id]["wins"] += 1

    # Сортируем: сначала по победам, потом по сумме баллов
    sorted_stats = sorted(
        stats.items(), 
        key=lambda x: (x[1]["wins"], x[1]["points"]), 
        reverse=True
    )
    
    return [
        {"place": i+1, "athlete_id": s[0], "wins": s[1]["wins"], "points": s[1]["points"]}
        for i, s in enumerate(sorted_stats)
    ]



async def generate_full_bracket(category_id: int, t_db: AsyncSession):
    # 1. Получаем атлетов
    res = await t_db.execute(select(DraftAssignment).where(DraftAssignment.category_id == category_id))
    athlete_ids = [a.athlete_id for a in res.scalars().all()]
    n = len(athlete_ids)
    
    if n < 2: return "Мало участников"

    # 2. РАССЧИТЫВАЕМ СЕТКУ (Для 5 это 8)
    grid_size = 2**math.ceil(math.log2(n)) # 2^3 = 8
    total_rounds = int(math.log2(grid_size)) # 3 раунда
    
    # Сортируем раунды от Финала (3) к Началу (1)
    tree = {r: [] for r in range(1, total_rounds + 1)}
    
    # Общее число матчей в олимпийской системе = grid_size - 1
    # Для 5 чел: 8 - 1 = 7 матчей всего
    match_number_counter = grid_size - 1 

    # 3. ГЕНЕРАЦИЯ ПУСТОГО КАРКАСА (сверху вниз)
    prev_round_matches = []
    for r in range(total_rounds, 0, -1):
        num_matches_in_round = 2**(total_rounds - r)
        current_round_matches = []
        
        for i in range(num_matches_in_round):
            m = Match(
                category_id=category_id,
                round_number=r,
                number=match_number_counter, # Будут номера 7, 6, 5... 1
                is_finished=False,
                aka_id=None, shiro_id=None
            )
            t_db.add(m)
            current_round_matches.append(m)
            match_number_counter -= 1
            
            # Связываем с матчем в СЛЕДУЮЩЕМ раунде
            if prev_round_matches:
                parent = prev_round_matches[i // 2]
                m.next_match_id = parent.id # Используйте await t_db.flush() после создания каждого раунда
                m.next_match_position = 1 if i % 2 == 0 else 2
        
        tree[r] = current_round_matches
        prev_round_matches = current_round_matches
        await t_db.flush() # Получаем ID для следующей итерации

    # Создаем бой за 3-е место
    # Он проходит в том же раунде, что и финал (total_rounds)
    third_place_match = Match(
        category_id=category_id,
        round_number=total_rounds, # Тот же раунд, что у финала
        number=grid_size,          # Номер после финала (например, 8)
        is_finished=False,
        is_repechage=True,         # Флаг для отличия от главного финала
        aka_id=None,
        shiro_id=None,
        aka_score=0,
        shiro_score=0
    )
    t_db.add(third_place_match)
    
    # 4. РАССТАНОВКА УЧАСТНИКОВ В РАУНД 1
    import random
    random.shuffle(athlete_ids)
    
    # Те, кто дерутся в R1: (5 - 4) * 2 = 2 человека. Остальные 3 ждут в R2.
    num_fights_r1 = n - (grid_size // 2)
    num_athletes_r1 = num_fights_r1 * 2
    
    r1_matches = sorted(tree[1], key=lambda x: x.number)
    
    # Заполняем только реальные бои Раунда 1
    for i in range(num_fights_r1):
        m = r1_matches[i]
        m.aka_id = athlete_ids[i*2]
        m.shiro_id = athlete_ids[i*2 + 1]

    # Остальные матчи Раунда 1 помечаем как технические (пройденные)
    for i in range(num_fights_r1, len(r1_matches)):
        r1_matches[i].is_finished = True

    # 5. РАССАЖИВАЕМ "ЖДУЩИХ" (Waiters) СРАЗУ В РАУНД 2
    waiters = athlete_ids[num_athletes_r1:]
    waiter_ptr = 0
    
    # Проходим по свободным слотам Раунда 2
    for m_r2 in tree[2]:
        # Если в этот слот AKA не ведет живой бой из R1 - сажаем ждущего
        if not any(m.next_match_id == m_r2.id and m.next_match_position == 1 and not m.is_finished for m in tree[1]):
            if waiter_ptr < len(waiters):
                m_r2.aka_id = waiters[waiter_ptr]
                waiter_ptr += 1
        # То же самое для SHIRO
        if not any(m.next_match_id == m_r2.id and m.next_match_position == 2 and not m.is_finished for m in tree[1]):
            if waiter_ptr < len(waiters):
                m_r2.shiro_id = waiters[waiter_ptr]
                waiter_ptr += 1

    await t_db.commit()


async def generate_all_kumite_horizontal(tournament_id: int, t_db: AsyncSession):
    # 1. Очистка старых данных
    await t_db.execute(delete(Match))
    
    # 2. Сбор категорий и атлетов
    cat_res = await t_db.execute(select(Category).where(Category.discipline == "kumite"))
    categories = cat_res.scalars().all()
    
    global_num = 1
    category_data = []

    for cat in categories:
        assign_res = await t_db.execute(
            select(DraftAssignment).where(DraftAssignment.category_id == cat.id)
        )
        athlete_ids = [a.athlete_id for a in assign_res.scalars().all()]
        n = len(athlete_ids)
        if n < 2: continue

        grid_size = 2**math.ceil(math.log2(n))
        total_rounds = int(math.log2(grid_size))
        random.shuffle(athlete_ids)

        # Алгоритм идеального распределения позиций (0, 7, 3, 4...)
        def get_order(size):
            if size == 2: return [0, 1]
            prev = get_order(size // 2)
            res = []
            for x in prev:
                res.extend([x, size - 1 - x])
            return res

        order = get_order(grid_size)
        slots = [None] * grid_size
        for i in range(n):
            slots[order[i]] = athlete_ids[i]

        category_data.append({
            "cat_id": cat.id,
            "slots": slots,
            "grid_size": grid_size,
            "total_rounds": total_rounds,
            "tree": {r: {} for r in range(1, total_rounds + 1)} # Используем dict для выборочных матчей
        })

    # 3. ГЕНЕРАЦИЯ МАТЧЕЙ СЛОЯМИ (начиная с финалов и вниз к R1)
    # Сначала создаем структуру всех возможных матчей со 2-го раунда до финала
    for data in category_data:
        for r in range(2, data["total_rounds"] + 1):
            num_matches = data["grid_size"] // (2**r)
            for i in range(num_matches):
                m = Match(
                    category_id=data["cat_id"],
                    round_number=r,
                    number=0, # Временно
                    is_finished=False
                )
                t_db.add(m)
                data["tree"][r][i] = m
        await t_db.flush()

    # 4. СВЯЗЫВАНИЕ И ЗАПОЛНЕНИЕ УЧАСТНИКОВ
    for data in category_data:
        # Связываем дерево (R2 -> R3 -> ... -> Final)
        for r in range(2, data["total_rounds"]):
            for i, m in data["tree"][r].items():
                parent = data["tree"][r+1][i // 2]
                m.next_match_id = parent.id
                m.next_match_position = 1 if i % 2 == 0 else 2

        # РАССАДКА И СОЗДАНИЕ МАТЧЕЙ R1 ТОЛЬКО ПРИ НАЛИЧИИ ПАРЫ
        for i in range(data["grid_size"] // 2):
            aka = data["slots"][i*2]
            shiro = data["slots"][i*2 + 1]
            
            # Находим матч R2, в который ведет этот путь
            m_r2 = data["tree"][2][i // 2] if data["total_rounds"] >= 2 else None
            pos_in_r2 = 1 if i % 2 == 0 else 2

            if aka and shiro:
                # Есть пара -> Создаем реальный матч в Раунде 1
                m_r1 = Match(
                    category_id=data["cat_id"],
                    round_number=1,
                    aka_id=aka,
                    shiro_id=shiro,
                    number=global_num,
                    is_finished=False
                )
                if m_r2:
                    m_r1.next_match_id = m_r2.id
                    m_r1.next_match_position = pos_in_r2
                t_db.add(m_r1)
                global_num += 1
            else:
                # Пары нет (один из них None) -> Спортсмен сразу в Раунд 2
                winner_id = aka or shiro
                if m_r2:
                    if pos_in_r2 == 1: m_r2.aka_id = winner_id
                    else: m_r2.shiro_id = winner_id
                # Если раунд всего один (финал), обрабатывается отдельно в логике турнира

        # 5. НУМЕРАЦИЯ ОСТАЛЬНЫХ МАТЧЕЙ (R2+)
        for r in range(2, data["total_rounds"] + 1):
            for i in sorted(data["tree"][r].keys()):
                data["tree"][r][i].number = global_num
                global_num += 1

        # 6. БОЙ ЗА 3 МЕСТО
        third_place = Match(
            category_id=data["cat_id"],
            round_number=data["total_rounds"],
            number=global_num,
            is_repechage=True
        )
        t_db.add(third_place)
        global_num += 1

    await t_db.commit()
    return {"status": "success", "total_matches": global_num - 1}

async def fill_tournament_summary(t_db):
    # 1. Загружаем только подтвержденных (явившихся) участников
    result = await t_db.execute(
        select(Athlete).where(Athlete.is_present == True)
    )
    athletes = result.scalars().all()
    
    total_count = len(athletes)
    stats = {} # Словарь для хранения групп: {(пол, возрастная_группа): кол-во}
    
    today = date.today()
    
    for a in athletes:
        # Считаем возраст на текущий момент (или на дату турнира)
        age = today.year - a.birth_date.year
        
        # Определяем категорию (пример: 8-9, 10-11 и т.д.)
        if 8 <= age <= 9: age_group = "8-9 лет"
        elif 10 <= age <= 11: age_group = "10-11 лет"
        elif 12 <= age <= 13: age_group = "12-13 лет"
        else: age_group = "другие"
        
        gender_label = "мальчиков" if a.gender == "male" else "девочек"
        
        key = (gender_label, age_group)
        stats[key] = stats.get(key, 0) + 1

    # 2. Формируем итоговую строку
    parts = []
    # Сортируем для красивого вывода (сначала мальчики по возрасту, потом девочки)
    for gender in ["мальчиков", "девочек"]:
        group_parts = []
        for g_name, a_range in sorted(stats.keys()):
            if g_name == gender:
                group_parts.append(f"{a_range} {stats[(g_name, a_range)]} человек")
        if group_parts:
            parts.append(f"{gender} " + ", ".join(group_parts))

    summary_text = f"{total_count} человек, из них: " + "; ".join(parts)

    return summary_text

async def get_formatted_winners_by_category(tournament_id: int, t_db: AsyncSession):
    # 1. Загружаем все категории турнира вместе с победителями, атлетами и командами
    result = await t_db.execute(
        select(Category)
        .where(Category.tournament_id == tournament_id)
        .options(
            selectinload(Category.winners).options(
                selectinload(Winner.athlete),
                selectinload(Winner.team)
            )
        )
    )
    categories = result.scalars().unique().all()

    formatted_results = []

    for cat in categories:
        if not cat.winners:
            continue
            
        # Сортируем победителей по местам (1, 2, 3...)
        sorted_winners = sorted(cat.winners, key=lambda x: x.place)
        
        # Собираем части строки для каждого места
        place_strings = []
        for w in sorted_winners:
            # Определяем имя (Атлет или Команда)
            if w.team_id and w.team:
                name = f"Группа: {w.team.name or 'Без названия'}"
            elif w.athlete:
                name = f"{w.athlete.last_name} {w.athlete.first_name}"
            else:
                name = "Неизвестно"
                
            place_strings.append(f"{w.place} место - {name}")

        # Соединяем всё в одну строку для категории
        # Формат: "Категория 8-9 лет: 1 место - Иванов, 2 место - Петров..."
        line = f'"{cat.name}" ' + " ".join([f'"{ps}"' for ps in place_strings])
        formatted_results.append(line)

    return formatted_results