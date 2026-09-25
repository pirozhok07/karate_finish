import pandas as pd
from io import BytesIO
from datetime import datetime
from app.child.models.athlete import Athlete

def parse_athletes_excel(file_content: bytes):
    df = pd.read_excel(BytesIO(file_content))
    df.columns = [str(c).lower().strip() for c in df.columns]
    
    all_athletes = []
    teams_temp = {} # {team_name: [Athlete, Athlete, Athlete]}

    for _, row in df.iterrows():
        def get_val(key):
            val = row.get(key)
            return str(val).strip() if pd.notna(val) else None

        bday = row.get('дата рождения')
        if isinstance(bday, str):
            try: bday = datetime.strptime(bday, "%d.%m.%Y").date()
            except: bday = None
        elif hasattr(bday, 'date'):
            bday = bday.date()

        athlete = Athlete(
            last_name=get_val('фамилия'),
            first_name=get_val('имя'),
            middle_name=get_val('отчество'),
            birth_date=bday,
            weight_preview=get_val('вес'),
            gender="male" if "м" in str(get_val('пол') or "").lower() else "female",
            club=get_val('клуб'),
            rank_sport=get_val('разряд'),
            rank_kyu=get_val('кю'),
            coach=get_val('тренер'),
            is_kata=1 if get_val('личка') else 0,
            is_team= 1 if get_val('id_team') else 0,
            is_kumite=1 if get_val('кумите') else 0
        )

        all_athletes.append(athlete)

        # Группируем по имени команды, если оно есть
        group_id = get_val('id_team') # Номер команды из Excel
        if athlete.is_team and group_id:
            if group_id not in teams_temp:
                teams_temp[group_id] = []
            teams_temp[group_id].append(athlete)
        

 # 5. Формируем финальный teams_dict с автоматическими именами
    teams_dict = {}
    for g_id, members in teams_temp.items():
        # Сортируем фамилии по алфавиту для красоты и создаем имя
        last_names = sorted([m.last_name for m in members])
        generated_name = ", ".join(last_names) # "Иванов, Петров, Сидоров"
        
        teams_dict[g_id] = {
            "name": generated_name,
            "members": members
        }

    return all_athletes, teams_dict


#  # 3. ЛОГИКА ФЛАГОВ (Личка / Команда)
#         # Проверяем колонки 'личка' и 'команда'. Считаем True, если там '1', '+', 'да' или 'x'
#         def is_checked(key):
#             val = row.get(key)
#             if pd.isna(val): return False
#             # Превращаем в строку, убираем .0 (для чисел из Excel) и пробелы
#             val_str = str(val).lower().replace('.0', '').strip()
#             return val_str in ['1', '+', 'да', 'x', 'true', 'v', 'yes']
        
#         # Динамически добавляем атрибуты к объекту (они понадобятся при сохранении в БД)
#         athlete._is_personal = is_checked('личка')
#         athlete._is_team = is_checked('команда')
        
#         all_athletes.append(athlete)

#         # Группируем по имени команды, если оно есть
#         group_id = get_val('id_team') # Номер команды из Excel
#         if athlete._is_team and group_id:
#             if group_id not in teams_temp:
#                 teams_temp[group_id] = []
#             teams_temp[group_id].append(athlete)
        

#  # 5. Формируем финальный teams_dict с автоматическими именами
#     teams_dict = {}
#     for g_id, members in teams_temp.items():
#         # Сортируем фамилии по алфавиту для красоты и создаем имя
#         last_names = sorted([m.last_name for m in members])
#         generated_name = ", ".join(last_names) # "Иванов, Петров, Сидоров"
        
#         teams_dict[g_id] = {
#             "name": generated_name,
#             "members": members
#         }

    # return all_athletes, teams_dict