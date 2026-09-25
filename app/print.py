from http.client import HTTPException, HTTPResponse
import os

from openpyxl import Workbook, load_workbook
from app.child.models.athlete import Athlete
from app.child.models.category import Category
from app.child.models.draft import DraftAssignment
from app.child.models.match import Match
from app.child.models.round import Round
from app.child.models.score import Score
from app.child.models.team import Team
from app.child.models.winner import Winner
from app.child.services.service import fill_tournament_summary
from app.database import get_db, get_t_db
from app.tournament_main.model import Tournament
from fastapi import APIRouter, Request, Depends, Response
from sqlalchemy import select, exists, or_ , not_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.templating import Jinja2Templates
from datetime import date
from collections import defaultdict
from sqlalchemy.orm import selectinload, contains_eager
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from io import BytesIO
from fastapi.responses import StreamingResponse

from openpyxl.utils import get_column_letter 
from app.child.services.for_kumite import TEMPLATES

# Импортируй свои модели и зависимость БД

router = APIRouter(prefix="/view/{tournament_id}", tags=["print"])
templates = Jinja2Templates(directory="templates")

@router.get("/print")
async def print_athletes_report(
    request: Request, 
    tournament_id: int, 
    t_db: AsyncSession = Depends(get_t_db),
    db: AsyncSession = Depends(get_db)
):
    
    # Загружаем турнир
    t_res = await db.execute(select(Tournament).where(Tournament.id == tournament_id))
    tournament = t_res.scalar_one_or_none()

    if not tournament:
        raise HTTPException(status_code=404, detail="Турнир не найден")

    res = defaultdict(list)
    result = await t_db.execute(select(Category).options(
            selectinload(Category.rounds).selectinload(Round.scores).selectinload(Score.athlete)
        ))
    categories = list(result.scalars().all())
    for cat in categories:
        res_name = cat.name
        for r in cat.rounds:
            for a in r.scores:
                res[res_name].append(a.athlete)

    # 3. Сортируем участников внутри каждой категории по фамилии
    for cat in res:
        res[cat].sort(key=lambda x: x.last_name.lower())

    return templates.TemplateResponse("print_athletes.html", {
        "request": request,
        "grouped_athletes": dict(sorted(res.items())), # Сортируем сами категории
        "t_id": tournament_id,
        "t_name": f'{tournament.type} "{tournament.title}"', 
        "t_desc": tournament.description, 
        "t_date": date.today().strftime("%d.%m.%Y"),
        "t_judge": tournament.judge, 
        "t_secretary": tournament.secretary, 
    })

@router.get("/print_scores")
async def print_athletes_report(
    request: Request, 
    tournament_id: int, 
    t_db: AsyncSession = Depends(get_t_db),
    db: AsyncSession = Depends(get_db)
):
    
    # Загружаем турнир
    t_res = await db.execute(select(Tournament).where(Tournament.id == tournament_id))
    tournament = t_res.scalar_one_or_none()
    
    if not tournament:
        raise HTTPException(status_code=404, detail="Турнир не найден")

    # 2. Загружаем оценки вместе с данными атлетов и раундов
    # Используем joinedload для оптимизации (чтобы не было кучи запросов в цикле)
    result = await t_db.execute(
        select(Score)
        .options(selectinload(Score.athlete))
        .options(selectinload(Score.round).selectinload(Round.category))
        .order_by(Score.place.asc(), Score.total_score.desc())
    )
    all_scores = result.scalars().all()

    result = await t_db.execute(
            select(Category).options(
                selectinload(Category.rounds)
                .selectinload(Round.scores)
                .selectinload(Score.athlete)
            )
        )
    categories = result.scalars().all()

    grouped_scores = defaultdict(list)
    for i in all_scores:
        athlete=i.athlete
        cat_key=i.round.category
        grouped_scores[cat_key].append(i)

    # 3. Группируем по категориям
    # Если в модели Score нет прямого названия категории, берем его через athlete или round
    return templates.TemplateResponse("print_scores.html", {
        "request": request,
        "categories": categories,
        "grouped_scores": dict(grouped_scores),
        "t_id": tournament_id,
        "t_name": f'{tournament.type} "{tournament.title}"', 
        "t_desc": tournament.description, 
        "t_date": date.today().strftime("%d.%m.%Y"),
        "t_judge": tournament.judge, 
        "t_secretary": tournament.secretary, 
    })


# @router.get("/export-results-excel")
# async def export_results_excel(
#     tournament_id: int, 
#     t_db: AsyncSession = Depends(get_t_db),
#     main_db: AsyncSession = Depends(get_db)
# ):
#     # 1. Загружаем данные турнира и результаты
#     t_res = await main_db.execute(select(Tournament).where(Tournament.id == tournament_id))
#     tournament = t_res.scalar_one_or_none()
    
#     result = await t_db.execute(
#         select(Score).options(selectinload(Score.athlete))
#         .order_by(Score.place.asc(), Score.total_score.desc())
#     )
#     scores_all = result.scalars().all()

#     # Группируем по категориям (Пол + Возраст)
#     grouped = {}
#     for s in scores_all:
#         age = date.today().year - s.athlete.birth_date.year
#         cat_name = f"{s.athlete.gender.upper()} {age} лет"
#         if cat_name not in grouped: grouped[cat_name] = []
#         grouped[cat_name].append(s)

#     # 2. Создаем книгу Excel
#     wb = Workbook()
#     wb.remove(wb.active) # Удаляем стандартный лист

#     # Стили для оформления "как в протоколе"
#     thin_side = Side(border_style="thin", color="000000")
#     thick_side = Side(border_style="medium", color="000000")
#     bold_border = Border(left=thin_side, top=thin_side, right=thin_side, bottom=thin_side)
#     header_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")

#     for cat_name, members in grouped.items():
#         ws = wb.create_sheet(title=cat_name[:30]) # Ограничение Excel на длину имени листа
        
#         # Шапка документа
#         ws.merge_cells('A1:J1')
#         ws['A1'] = tournament.title
#         ws['A1'].font = Font(bold=True, size=14)
#         ws['A1'].alignment = Alignment(horizontal="center")

#         ws.merge_cells('A2:J2')
#         ws['A2'] = f"г. Москва  |  Дата: {tournament.event_date.strftime('%d.%m.%Y')}"
#         ws['A2'].alignment = Alignment(horizontal="center")

#         ws.merge_cells('A3:J3')
#         ws['A3'] = f"ПРОТОКОЛ РЕЗУЛЬТАТОВ: {cat_name}"
#         ws['A3'].font = Font(bold=True, size=12)
#         ws['A3'].alignment = Alignment(horizontal="center")

#         # Заголовки таблицы (строка 5)
#         headers = ["№", "Фамилия Имя", "Клуб", "С1", "С2", "С3", "С4", "С5", "ИТОГО", "МЕСТО"]
#         ws.append([]) # пустая строка 4
#         ws.append(headers)

#         # Стилизуем шапку таблицы
#         for cell in ws[5]:
#             cell.font = Font(bold=True)
#             cell.border = bold_border
#             cell.fill = header_fill
#             cell.alignment = Alignment(horizontal="center")

#         # Данные участников
#         for idx, s in enumerate(members, 1):
#             row = [
#                 idx, 
#                 f"{s.athlete.last_name} {s.athlete.first_name}",
#                 s.athlete.club or "-",
#                 s.s1, s.s2, s.s3, s.s4, s.s5,
#                 s.total_score,
#                 s.place or ""
#             ]
#             ws.append(row)
#             for cell in ws[ws.max_row]:
#                 cell.border = bold_border
#                 cell.alignment = Alignment(horizontal="center")

#         # Подписи внизу
#         start_footer = ws.max_row + 2
#         ws.merge_cells(f'A{start_footer}:C{start_footer}')
#         ws[f'A{start_footer}'] = f"Главный судья: ___________ / {tournament.judge} /"
        
#         ws.merge_cells(f'A{start_footer+1}:C{start_footer+1}')
#         ws[f'A{start_footer+1}'] = f"Главный секретарь: ___________ / {tournament.secretary} /"

#         # Настройка ширины колонок
#         ws.column_dimensions['B'].width = 30
#         ws.column_dimensions['C'].width = 20

#     # 3. Сохранение в буфер
#     stream = BytesIO()
#     wb.save(stream)
    
#     return Response(
#         content=stream.getvalue(),
#         media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#         headers={"Content-Disposition": f"attachment; filename=Results_{tournament_id}.xlsx"}
#     )


@router.get("/export-athletes-excel")
async def export_athletes_excel(
    tournament_id: int, 
    t_db: AsyncSession = Depends(get_t_db),
    main_db: AsyncSession = Depends(get_db)
):
    # 1. Загружаем данные турнира и атлетов
    tournament = await main_db.get(Tournament, tournament_id)

    result = await t_db.execute(
        select(Category)
        .where(
            exists()
            .where(DraftAssignment.category_id == Category.id)
            .where(
                or_(DraftAssignment.athlete.has(is_present = True),
                    and_(DraftAssignment.team_id.is_not(None),
                        DraftAssignment.team.has(
                            and_(
                                Team.members.any(is_present = True),
                                ~Team.members.any(is_present = False),
                            )
                        )
                    )
                )
            )
        )
        .options(
            selectinload(Category.draft_assignments).selectinload(DraftAssignment.athlete),
            selectinload(Category.draft_assignments).selectinload(DraftAssignment.team).selectinload(Team.members)
        )
    )
    categories = result.scalars().all()

    wb = load_workbook("data/temp_athlete.xlsx")
    template_sheet = wb.active

   # Заранее определяем стили
    thin = Side(border_style="thin")
    thick = Side(border_style="medium")
    
    header_font = Font(name='Times New Roman', size=11, bold=True)
    data_font = Font(name='Times New Roman', size=11)
    center_align = Alignment(horizontal="center", vertical="center")
    header_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
    left_align = Alignment(horizontal="left", vertical="center", indent=1)
    max_col=10
    for cat in categories:
        ws = wb.copy_worksheet(template_sheet)
        ws.title = cat.name[:30]

 # --- 1. ШАПКА ЛИСТА ---
        ws['A1'] = f'{tournament.type} "{tournament.title}"'
        # ws['A2'] = f'{tournament.description}'
        ws['H4'] = tournament.event_date.strftime("%d.%m.%Y")
        ws['A6'] = f'{cat.name}'
        if cat.discipline == 'kumite': 
            ws['A5'] = 'Протокол взвешивания'
            ws.column_dimensions['h'].hidden = False
        else:
            ws.column_dimensions['h'].hidden = True
        current_row = 8 
        if len(cat.draft_assignments) <= 0: continue
        for idx, data in enumerate(cat.draft_assignments, 1):
            
            if (data.athlete):
                a = data.athlete
                if(not a.is_present): continue
                row_data = [
                    idx,
                    a.last_name,
                    a.first_name,
                    a.middle_name,
                    a.birth_date.strftime("%d.%m.%Y"),
                    a.rank_kyu,
                    a.rank_sport,
                    a.weight_preview,
                    a.club,
                    a.coach
                ]
                for col_idx, value in enumerate(row_data, 1):
                    cell = ws.cell(row=current_row, column=col_idx, value=value)
                    cell.font = data_font
    #     
                    # Выравнивание: ФИО и Клуб по левому краю, остальное по центру
                    cell.alignment = left_align if col_idx in [2, 3, 4] else center_align
                    
                    # Границы данных
                    l = thick if col_idx == 1 else thin
                    r = thick if col_idx == max_col else thin
                    b = thick if idx == len(cat.draft_assignments) else thin
                    cell.border = Border(left=l, right=r, top=thin, bottom=b)
                    
                    # Формат для веса (0.0)
                    if col_idx == 8 and value != "":
                        cell.number_format = '0.0'
                current_row += 1
            else: 
                teams = data.team
                for ind, a in enumerate(teams.members, 1):
                    row_data = [
                        idx,
                        a.last_name,
                        a.first_name,
                        a.middle_name,
                        a.birth_date.strftime("%d.%m.%Y"),
                        a.rank_kyu,
                        a.rank_sport,
                        a.weight_preview,
                        a.club,
                        a.coach
                    ]
                    for col_idx, value in enumerate(row_data, 1):
                        cell = ws.cell(row=current_row, column=col_idx, value=value)
                        cell.font = data_font
        #     
                        # Выравнивание: ФИО и Клуб по левому краю, остальное по центру
                        cell.alignment = left_align if col_idx in [2, 3, 4] else center_align
                        
                        # Границы данных
                        l = thick if col_idx == 1 else thin
                        r = thick if col_idx == max_col else thin
                        b = thick if (idx == len(cat.draft_assignments)*3 or ind == 3) else thin
                        t = thick if (ind == 1) else thin
                        cell.border = Border(left=l, right=r, top=t, bottom=b)

                    if (ind == 3):
                        ws.merge_cells(start_row=current_row-2, start_column=1, end_row=current_row, end_column=1)
                        ws.cell(row=current_row-2, column=1).border = Border(left=thick, right=thin, top=thick, bottom=thick)
                        
                    current_row += 1
                


        for col_idx in range(1, 11):
            ws.cell(row=current_row, column=col_idx).border = Border(top=thick)

        current_row += 2 # Отступ между судьей и секретарем
        
        # Настройка шрифта для подписей
        footer_font = Font(name='Times New Roman', size=11, bold=True)
        signature_line = Border(bottom=Side(border_style="thin", color="000000"))
        # Подпись Главного судьи
        ws.cell(row=current_row, column=1, value="Главный судья").font = footer_font
        ws.cell(row=current_row, column=1).alignment = Alignment(horizontal="left")
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=2)
         # Создаем линию (объединяем колонки 2-4 и ставим нижнюю границу)
        ws.merge_cells(start_row=current_row, start_column=4, end_row=current_row, end_column=6)
        for col_idx in range(4, 7):
            ws.cell(row=current_row, column=col_idx).border = signature_line
        ws.merge_cells(start_row=current_row, start_column=9, end_row=current_row, end_column=10)
        ws.cell(row=current_row, column=9, value=f"{tournament.judge}").font = footer_font
        ws.cell(row=current_row, column=9).alignment = Alignment(horizontal="right")

        current_row += 2 # Отступ между судьей и секретарем

        # Подпись Главного секретаря
        ws.cell(row=current_row, column=1, value="Главный секретарь").font = footer_font
        ws.cell(row=current_row, column=1).alignment = Alignment(horizontal="left")
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=2)
         # Создаем линию (объединяем колонки 2-4 и ставим нижнюю границу)
        ws.merge_cells(start_row=current_row, start_column=4, end_row=current_row, end_column=6)
        for col_idx in range(4, 7):
            ws.cell(row=current_row, column=col_idx).border = signature_line
        ws.merge_cells(start_row=current_row, start_column=9, end_row=current_row, end_column=10)
        ws.cell(row=current_row, column=9, value=f"{tournament.secretary}").font = footer_font
        ws.cell(row=current_row, column=9).alignment = Alignment(horizontal="right")
        
        # Настройка параметров печати для этого листа
        ws.page_setup.orientation = ws.ORIENTATION_PORTRAIT
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
#     # --- 4. АВТОПОДБОР ШИРИНЫ ---
#     for col_idx in range(1, max_col + 1):
#         column_letter = get_column_letter(col_idx)
#         max_length = 0
#         for row in range(4, ws.max_row + 1):
#             cell = ws.cell(row=row, column=col_idx)
#             if cell.value:
#                 val_len = len(str(cell.value))
#                 if val_len > max_length: max_length = val_len
        
#         ws.column_dimensions[column_letter].width = min(max_length + 3, 40)

    wb.remove(template_sheet)
    
    stream = BytesIO()
    wb.save(stream)
    
    return Response(
        content=stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=Athletes_{tournament_id}.xlsx"}
    )


@router.get("/kumite-print", response_class=HTTPResponse)
async def print_category_bracket(
    request: Request,  
    tournament_id: int,
    t_db: AsyncSession = Depends(get_t_db),
    main_db: AsyncSession = Depends(get_db)
):
    # 1. Загружаем данные турнира и категорий со всеми раундами
    # Должна быть связь: Category -> Rounds -> Scores
    result = await t_db.execute(
        select(Athlete)
        .where(Athlete.is_present)
    )
    all_athletes = result.scalars().all()
    def find_athlete(athletes, id):
                        for athlete in athletes:
                            if athlete.id == id:
                                return athlete
                        return None
    result = await t_db.execute(
        select(Category)
        .join(Category.draft_assignments)
        .join(DraftAssignment.athlete)
        .where(
            Category.discipline == "kumite",
            Athlete.is_present == True
            )
        .options(contains_eager(Category.draft_assignments))
        .order_by(Category.id)
    )

    categories_athletes = result.unique().scalars().all()
    
    result = await t_db.execute(
        select(Category).where(
            Category.discipline == "kumite",
            exists().where(Match.category_id == Category.id)
        )
        .options(selectinload(Category.winners),selectinload(Category.matches).options(selectinload(Match.aka), selectinload(Match.shiro)))
        .order_by(Category.id)
    )
    
    categories_matches = result.scalars().all()
    tournament = await main_db.get(Tournament, tournament_id)
    
    wb = load_workbook("data/temp_kumite.xlsx")
    
    for category, athletes in zip(categories_matches, categories_athletes):
        
        count_athletes = len(athletes.draft_assignments)
        if count_athletes == 2:
            name_list = "len1"
            position = TEMPLATES[1]
        elif count_athletes == 3:
            name_list = "len3"
            position = TEMPLATES[3]
        elif count_athletes == 4:
            name_list = "len2"
            position = TEMPLATES[2]
        else:
            name_list = "len4"
            position = TEMPLATES[4]

        ws = wb.copy_worksheet(wb[name_list])
        ws.title = category.name[:30]
        ws['A1'] = f'{tournament.type} "{tournament.title}"'
        ws['A2'] = f'{tournament.description}'
        ws['H4'] = tournament.event_date.strftime("%d.%m.%Y")
        ws['A6'] = f'{category.name}'

        matches = category.matches
        matches.sort(key=lambda m: m.number)
        rounds = defaultdict(list)
        for match in matches:
            rounds[match.round_number].append(match)
        for round_num, matches in rounds.items():
            for it, match in enumerate(matches, 1):
                cell_aka_x, cell_aka_y = position[f"round_{round_num}"][f"match_{it}"]["aka"]
                cell_shiro_x, cell_shiro_y = position[f"round_{round_num}"][f"match_{it}"]["shiro"]
                cell_winner_x, cell_winner_y = position[f"round_{round_num}"][f"match_{it}"]["winner"]   
                
                aka = find_athlete(all_athletes, match.aka_id)
                shiro = find_athlete(all_athletes, match.shiro_id)
                if (cell_winner_x != None) and (cell_winner_y != None):
                    winner = find_athlete(all_athletes, match.winner_id)
                    ws.cell(cell_winner_x, cell_winner_y, value=f"{winner.first_name} {winner.last_name}")
                    ws.cell(cell_winner_x+1, cell_winner_y, value=winner.club)

                ws.cell(cell_aka_x, cell_aka_y, value=f"{aka.first_name} {aka.last_name}")
                ws.cell(cell_aka_x+1, cell_aka_y, value=aka.club)
                ws.cell(cell_shiro_x, cell_shiro_y, value=f"{shiro.first_name} {shiro.last_name}")
                ws.cell(cell_shiro_x+1, cell_shiro_y, value=shiro.club)

                
                cell_fiil_x = cell_aka_x if (match.winner_id == match.aka_id) else cell_shiro_x
                cell_fiil_y = cell_aka_y if (match.winner_id == match.aka_id) else cell_shiro_y
                color = "FF0000" if (match.winner_id == match.aka_id) else "0000FF"
                ws.cell(cell_fiil_x, cell_fiil_y).border = Border(
                    top=Side(border_style='thick', color=color),
                    right=Side(border_style='thick', color=color),
                    left=Side(border_style='thick', color=color),
                    ) 
                ws.cell(cell_fiil_x+1, cell_fiil_y).border = Border(
                    bottom=Side(border_style='thick', color=color),
                    right=Side(border_style='thick', color=color),
                    left=Side(border_style='thick', color=color),
                    ) 
            winners = category.winners
            winners.sort(key=lambda m: m.place)
            cell_winner_x, cell_winner_y = position["result"]  
            for i, win in enumerate(winners):
                winner = find_athlete(all_athletes, win.athlete_id)
                ws.cell(cell_winner_x + i, cell_winner_y, value=f"{winner.first_name} {winner.last_name} {winner.middle_name} ({winner.club})")
    
    stream = BytesIO()
    wb.save(stream)
    
    return Response(
        content=stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=Kumite_{tournament_id}.xlsx"}
    )


def set_border_to_range(ws, start_row, start_col, end_row, end_col, border_style):
    for r in range(start_row, end_row + 1):
        for c in range(start_col, end_col + 1):
            ws.cell(row=r, column=c).border = border_style

# Использование:
def set_outer_thick_border(ws, start_row, start_col, end_row, end_col):
    thick_side = Side(style='medium')
    
    for r in range(start_row, end_row + 1):
        for c in range(start_col, end_col + 1):
            # Получаем текущие границы ячейки (чтобы не стереть тонкие линии)
            current_border = ws.cell(row=r, column=c).border
            
            # Определяем стороны для замены на толстые
            left = thick_side if c == start_col else current_border.left
            right = thick_side if c == end_col else current_border.right
            top = thick_side if r == start_row else current_border.top
            bottom = thick_side if r == end_row else current_border.bottom
            
            # Применяем обновленную границу
            ws.cell(row=r, column=c).border = Border(left=left, right=right, top=top, bottom=bottom)


@router.get("/export-scores-excel")
async def export_scores_excel(
    tournament_id: int, 
    t_db: AsyncSession = Depends(get_t_db),
    main_db: AsyncSession = Depends(get_db)
):
    # 1. Загружаем данные турнира и категорий со всеми раундами
    # Должна быть связь: Category -> Rounds -> Scores
    result = await t_db.execute(
        select(Category).where(Category.discipline == "kata").options(
            selectinload(Category.rounds).selectinload(Round.scores).options(
            # 3. А уже ИЗ ОЦЕНОК подгружаем Атлета и Команду с её составом
            selectinload(Score.athlete),
            selectinload(Score.team).selectinload(Team.members)
        ),
        )
    )
    categories = result.scalars().all()
    
    tournament = await main_db.get(Tournament, tournament_id)

    wb = load_workbook("data/temp_kata.xlsx")
    template_sheet = wb.active

    # Заранее определяем стили
    thin = Side(border_style="thin")
    thick = Side(border_style="medium")
    
    header_font = Font(name='Times New Roman', size=11, bold=True)
    data_font = Font(name='Times New Roman', size=11)
    center_align = Alignment(horizontal="center", vertical="center")
    header_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
    
    for cat in categories:
        ws = wb.copy_worksheet(template_sheet)
        ws.title = cat.name[:30]

        ws['A1'] = f'{tournament.type} "{tournament.title}"'
        ws['A2'] = f'{tournament.description}'
        ws['H4'] = tournament.event_date.strftime("%d.%m.%Y")
        ws['A6'] = f'{cat.name}'
        
        current_row = 8 

        main_rounds = sorted([r for r in cat.rounds if not r.is_tie_break], key=lambda x: x.round_number)

        for rnd_idx, rnd in enumerate(main_rounds, 1):
            # Определяем максимальную колонку: 10 если финал (есть Место), иначе 9
            rounds_to_print = [rnd]
            
            # Ищем переигровки, привязанные к этому раунду (по parent_round_id)
            tie_breaks = sorted(
                [r for r in cat.rounds if r.is_tie_break and r.parent_round_id == rnd.id],
                key=lambda x: x.round_number
            )
            rounds_to_print.extend(tie_breaks)

            for sub_rnd in rounds_to_print:
                # Если это переигровка, меняем заголовок
                if sub_rnd.is_tie_break:
                    title_text = f"ПЕРЕИГРОВКА (к Раунду {rnd_idx})"
                    header_fill_color = "FFF5F5" # Легкий красный фон для переигровки
                else:
                    title_text = f"Раунд {rnd_idx}"
                    header_fill_color = "EDF2F7"

                # Определяем максимальную колонку: 10 если финал основного раунда, иначе 9
                max_col = 10 if (rnd_idx == 3 and not sub_rnd.is_tie_break) else 9

                # --- 1. Заголовок раунда (в жирной рамке) ---
                ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=max_col)
                header_cell = ws.cell(row=current_row, column=1, value=title_text)
                header_cell.alignment = center_align
                header_cell.font = Font(name='Times New Roman', size=12, bold=True, color="9B2C2C" if sub_rnd.is_tie_break else "000000")
                
                for c_idx in range(1, max_col + 1):
                    ws.cell(row=current_row, column=c_idx).border = Border(top=thick, left=thick if c_idx==1 else thin, right=thick if c_idx==max_col else thin, bottom=thin)
                current_row += 1

                # --- 2. Шапка таблицы (Двухуровневая) ---
                # Ключ - номер колонки. Важно: 1-№, 2-Имя, 3-Ката, 4-Оценки(4-8), 9-Итого, 10-Место
                headers = {
                    1: "№",
                    2: "Фамилия Имя, Клуб",
                    3: "Ката",
                    4: "Оценки судей",
                    9: "ИТОГО",
                    10: "МЕСТО"
                }

                for col_idx, text in headers.items():
                    if col_idx > max_col: continue
                    if col_idx == 4:
                        ws.merge_cells(start_row=current_row, start_column=col_idx, end_row=current_row, end_column=col_idx + 4)
                    else:
                        ws.merge_cells(start_row=current_row, start_column=col_idx, end_row=current_row + 1, end_column=col_idx)
                    cell = ws.cell(row=current_row, column=col_idx, value=text)
                    cell.font = header_font
                    cell.alignment = center_align

                # Подписи C1-C5
                for i, text in enumerate(["C1", "C2", "C3", "C4", "C5"]):
                    c_cell = ws.cell(row=current_row + 1, column=4 + i, value=text)
                    c_cell.font = header_font
                    c_cell.alignment = center_align 


                # --- 3. Стилизация Шапки (Границы и Заливка) ---
                for r_idx in range(current_row, current_row + 2):
                    for c_idx in range(1, max_col + 1):
                        cell = ws.cell(row=r_idx, column=c_idx)
                        cell.fill = header_fill
                        
                        l, r_s, t, b = thin, thin, thin, thin
                        if r_idx == current_row: t = thick
                        if r_idx == current_row + 1: b = thick
                        if c_idx < 4: 
                            l = thick 
                            r_s = thick 
                        if c_idx == max_col: r_s = thick

                        # Блок "Оценки судей" (колонки 4-8)
                        if 4 <= c_idx <= 8:
                            if r_idx == current_row: t = thick
                            if r_idx == current_row + 1: b = thick
                            if c_idx == 4: l = thick
                            if c_idx == 8: r_s = thick
                        
                        if c_idx == 9: 
                            l = thick 
                            r_s = thick # Жирная линия перед ИТОГО

                        cell.border = Border(left=l, right=r_s, top=t, bottom=b)

                current_row += 2 

                # --- 4. Данные участников ---
                for idx, s in enumerate(sub_rnd.scores, 1):
                    # Логика определения имени участника (Личник или Команда)
                    if s.team_id and s.team:
                        # Формируем строку: Название команды + Фамилии участников в скобках
                        participant_name = ", ".join([f"{m.last_name}" for m in s.team.members])
                        club_name = s.team.club or ""
                    else:
                        # Обычный личник
                        participant_name = f"{s.athlete.last_name} {s.athlete.first_name}"
                        club_name = s.athlete.club or ""

                    row_data = [
                        idx,
                        f"{participant_name} ({club_name})", # Объединяем имя и клуб для колонки "СПОРТСМЕН"
                        s.performance_kata or "",
                        s.s1, s.s2, s.s3, s.s4, s.s5,
                        s.total_score
        ]
                    if rnd_idx == 3:
                        row_data.append(s.place if s.place < 4 else "")

                    for col_idx, value in enumerate(row_data, 1):
                        cell = ws.cell(row=current_row, column=col_idx, value=value)
        
                        # ПРИМЕНЯЕМ ФОРМАТ 0.0 для колонок оценок (4-8) и ИТОГО (9)
                        if 4 <= col_idx <= 9:
                            cell.number_format = '0.0'
                            # Убеждаемся, что значение передано как число (float), иначе формат не сработает
                            if value is not None and value != "":
                                try:
                                    cell.value = float(value)
                                except ValueError:
                                    pass
                        cell.font = data_font
                        cell.alignment = Alignment(horizontal="left" if col_idx == 2 else "center", vertical="center")

                        l, r_s, t, b = thin, thin, thin, thin
                        if col_idx < 4: 
                            l = thick
                            r_s = thick
                        if col_idx == max_col: r_s = thick
                        
                        # Жирные разделители блоков
                        if col_idx == 4: l = thick # Перед оценками
                        if col_idx == 8: r_s = thick # После оценок
                        if col_idx == 9: 
                            l = thick # Перед итого
                            r_s = thick
                        if idx == len(sub_rnd.scores): b = thick # Низ таблицы

                        cell.border = Border(left=l, right=r_s, top=t, bottom=b)

                    current_row += 1
                
                current_row += 1
        
        # Настройка шрифта для подписей
        footer_font = Font(name='Times New Roman', size=11, bold=True)
        signature_line = Border(bottom=Side(border_style="thin", color="000000"))
        # Подпись Главного судьи
        ws.cell(row=current_row, column=1, value="Главный судья").font = footer_font
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=2)
         # Создаем линию (объединяем колонки 2-4 и ставим нижнюю границу)
        ws.merge_cells(start_row=current_row, start_column=3, end_row=current_row, end_column=5)
        for col_idx in range(3, 6):
            ws.cell(row=current_row, column=col_idx).border = signature_line
        ws.merge_cells(start_row=current_row, start_column=7, end_row=current_row, end_column=10)
        ws.cell(row=current_row, column=7, value=f"{tournament.judge}").font = footer_font
        ws.cell(row=current_row, column=7).alignment = Alignment(horizontal="right")

        current_row += 2 # Отступ между судьей и секретарем

        # Подпись Главного секретаря
        ws.cell(row=current_row, column=1, value="Главный секретарь").font = footer_font
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=2)
         # Создаем линию (объединяем колонки 2-4 и ставим нижнюю границу)
        ws.merge_cells(start_row=current_row, start_column=3, end_row=current_row, end_column=5)
        for col_idx in range(3, 6):
            ws.cell(row=current_row, column=col_idx).border = signature_line
        ws.merge_cells(start_row=current_row, start_column=7, end_row=current_row, end_column=10)
        ws.cell(row=current_row, column=7, value=f"{tournament.secretary}").font = footer_font
        ws.cell(row=current_row, column=7).alignment = Alignment(horizontal="right")
        
        # Настройка параметров печати для этого листа
        ws.page_setup.orientation = ws.ORIENTATION_PORTRAIT
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        # ws.page_setup.fitToPage = True

    # # --- АВТОМАТИЧЕСКАЯ ШИРИНА КОЛОНОК ---
    # for sheet in wb.worksheets:
    #     # Проходим по индексам колонок от 1 до max_column
    #     for col_idx in range(1, sheet.max_column + 1):
    #         max_length = 0
    #         column_letter = get_column_letter(col_idx)
            
    #         # Перебираем все ячейки в данной колонке
    #         for row in range(1, sheet.max_row + 1):
    #             cell = sheet.cell(row=row, column=col_idx)
                
    #             # Пропускаем объединенные ячейки (кроме главной в объединении)
    #             if hasattr(cell, 'value'): 
    #                 try:
    #                     if cell.value:
    #                         val_len = len(str(cell.value))
    #                         if val_len > max_length:
    #                             max_length = val_len
    #                 except:
    #                     pass
            
    #         # Логика настройки ширины
    #         if column_letter == 'B': # Фамилия Имя
    #             adjusted_width = min(max_length + 2, 50)
    #         elif column_letter == 'C': # Ката
    #             adjusted_width = min(max_length + 2, 20)
    #         elif col_idx >= 4 and col_idx <= 8: # Колонки оценок C1-C5
    #             adjusted_width = 5 # Делаем их узкими и одинаковыми
    #         else:
    #             adjusted_width = max_length + 2
                
    #         sheet.column_dimensions[column_letter].width = adjusted_width

    wb.remove(template_sheet)
    
    stream = BytesIO()
    wb.save(stream)
    
    return Response(
        content=stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=Kata_{tournament_id}.xlsx"}
    )


@router.get("/export-main-excel")
async def export_tournament_info(
    tournament_id: int, 
    t_db: AsyncSession = Depends(get_t_db),
    main_db: AsyncSession = Depends(get_db)
):
    
    template_path="data/temp_main.xlsx"
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Файл шаблона не найден по адресу: {template_path}")

    # Загружаем шаблон
    wb = load_workbook(template_path)
    # Предполагаем, что первый лист предназначен для общей информации
    ws = wb.active 

    tournament = await main_db.get(Tournament, tournament_id)



    # Пример маппинга данных в конкретные ячейки шаблона
    # (Измените адреса ячеек A1, B3 и т.д. под ваш реальный шаблон)
    data_mapping = {
        'E8': f'{tournament.type} "{tournament.title}"',
        'E9': tournament.description,
        'E10': tournament.description,
        'E11': tournament.event_date.strftime("%d.%m.%Y"),
        # 'E12': tournament.adress,
        'E13': tournament.judge,
        'E14': tournament.secretary,
        'E15': await fill_tournament_summary(t_db),
    }

    for cell_address, value in data_mapping.items():
        cell = ws[cell_address]
        cell.value = value
        # Сохраняем перенос текста для длинных описаний, если нужно
        cell.alignment = Alignment(wrap_text=True, vertical="center")

    ws['A1'] = f'{tournament.type} "{tournament.title}"'
    ws['A2'] = f'{tournament.description}'
    ws['H4'] = tournament.event_date.strftime("%d.%m.%Y")
    ws['H18'] =f'{tournament.judge}'
    ws['H20'] =f'{tournament.secretary}'

    # Сохраняем результат в новый файл
    
    stream = BytesIO()
    wb.save(stream)
    
    return Response(
        content=stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=Main_{tournament_id}.xlsx"}
    )


@router.get("/export-results-excel")
async def export_results_excel(
    tournament_id: int, 
    t_db: AsyncSession = Depends(get_t_db),
    main_db: AsyncSession = Depends(get_db)
):
    # 1. Загружаем данные турнира и результаты с победителями
    tournament = await main_db.get(Tournament, tournament_id)
    # Загружаем категории вместе с победителями, их атлетами и командами (с составом)
    result = await t_db.execute(
        select(Category)
        .options(
            selectinload(Category.winners).options(
                selectinload(Winner.athlete),
                selectinload(Winner.team).selectinload(Team.members)
            )
        )
    )
    categories = result.scalars().unique().all()
    
    # Загружаем шаблон (используем тот же temp_athlete или создайте копию temp_winner)
    wb = load_workbook("data/temp_total_result.xlsx")

    # Стили из вашего примера
    thin = Side(border_style="thin")
    thick = Side(border_style="medium")
    data_font = Font(name='Times New Roman', size=11)
    footer_font = Font(name='Times New Roman', size=11, bold=True)
    center_align = Alignment(horizontal="center", vertical="center")
    left_align = Alignment(horizontal="left", vertical="center", indent=1)
    signature_line = Border(bottom=Side(border_style="thin", color="000000"))
    light_border = Border(left=thin, top=thin, right=thin, bottom=thin)

    max_col = 4 # Для протокола результатов достаточно: №, Место, ФИО/Команда, Клуб

    ws = wb.active
    ws.title = f"Результаты"


    # --- 1. ШАПКА ЛИСТА (Ваш стиль) ---
    ws['A1'] = f'{tournament.type} "{tournament.title}"'
    ws['A2'] = f'{tournament.description}'
    ws['F4'] = tournament.event_date.strftime("%d.%m.%Y")

    current_row = 8
    table_start_row = current_row 
    for cat in categories:
        if not cat.winners:
            continue

        # 1. Определяем высоту блока категории
        # Если есть команды по 3 чел, то на каждое из 3-х мест (1,2,3) уходит по 3 строки = 9 строк.
        # Иначе (личники) 3 места по 1 строке = 3 строки.
        is_team_cat = any(w.team_id for w in cat.winners)
        rows_per_place = 3 if is_team_cat else 1
        total_cat_rows = (len(cat.winners) * rows_per_place) - 1 # -1 для индексации merge

        cat_value = f"Кёкусин-ката-группа,\n{cat.name}" if is_team_cat else f"Кёкусин-ката,\n{cat.name}"
        
        # Объединяем ячейку категории (Колонка 2)
        ws.cell(row=current_row, column=2, value=cat_value).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.merge_cells(start_row=current_row, start_column=2, end_row=current_row + total_cat_rows, end_column=2)
        set_border_to_range(ws, current_row, 2, current_row + total_cat_rows, 2, light_border)

        places = sorted(cat.winners, key=lambda x: x.place)

        for w in places:
            # Начальная строка для текущего места
            place_start_row = current_row
            
            # Объединяем ячейку "Место" (Колонка 3)
            ws.cell(row=place_start_row, column=3, value=f"{int(w.place)} место").alignment = Alignment(horizontal="center", vertical="center")
            ws.merge_cells(start_row=place_start_row, start_column=3, end_row=place_start_row + rows_per_place - 1, end_column=3)
            set_border_to_range(ws, place_start_row, 3, place_start_row + rows_per_place - 1, 3, light_border)

            # Подготавливаем список участников для вывода
            if w.team_id and w.team:
                participants = w.team.members[:3] # Берем первых троих
                club_val = w.team.club or ""
            else:
                participants = [w.athlete] # Один личник
                club_val = w.athlete.club or ""

            # Выводим строки участников (1 или 3)
            for i, person in enumerate(participants):
                row = place_start_row + i
                
                # ФИО (Колонка 4)
                name = f"{person.last_name} {person.first_name} {person.middle_name or ''}"
                ws.cell(row=row, column=4, value=name).border = light_border
                
                # Дата рождения (Колонка 5)
                bday = person.birth_date.strftime("%d.%m.%Y") if person.birth_date else ""
                ws.cell(row=row, column=5, value=bday).border = light_border
                ws.cell(row=row, column=5, value=bday).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                
                # Клуб (Колонка 6)
                ws.cell(row=row, column=6, value=club_val).border = light_border
                ws.cell(row=row, column=6, value=club_val).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

            # Если это личник, мы просто переходим на +1 строку. 
            # Если команда, мы заполнили 3 строки, но нам нужно объединить Клуб, если он общий.
            if is_team_cat:
                # Объединяем Клуб для команды (Колонка 6)
                ws.merge_cells(start_row=place_start_row, start_column=6, end_row=place_start_row + rows_per_place - 1, end_column=6)
                ws.cell(row=place_start_row, column=6).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                set_border_to_range(ws, place_start_row, 6, place_start_row + rows_per_place - 1, 6, light_border)

            current_row += rows_per_place






    set_outer_thick_border(ws, table_start_row, 2, current_row - 1, 6)
    # --- 3. ПОДПИСИ (Ваш стиль) ---
    current_row += 2
    for title, person in [("Главный судья", tournament.judge), ("Главный секретарь", tournament.secretary)]:
        ws.cell(row=current_row, column=1, value=title).font = footer_font
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=2)
        
        # Линия подписи
        ws.merge_cells(start_row=current_row, start_column=4, end_row=current_row, end_column=5)
        for c in range(4, 6):
            ws.cell(row=current_row, column=c).border = signature_line
            
        # ФИО справа
        cell_name = ws.cell(row=current_row, column=6, value=person)
        ws.merge_cells(start_row=current_row, start_column=6, end_row=current_row, end_column=7)
        cell_name.font = footer_font
        cell_name.alignment = Alignment(horizontal="right")
        current_row += 2

        # Настройка листа
        # ws.page_setup.orientation = ws.ORIENTATION_PORTRAIT
        # ws.column_dimensions['B'].width = 12
        # ws.column_dimensions['C'].width = 45
        # ws.column_dimensions['D'].width = 25

    
    stream = BytesIO()
    wb.save(stream)
    return Response(
        content=stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=Winners_{tournament_id}.xlsx"}
    )