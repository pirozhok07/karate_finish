from app.child.models.round import Round
from app.child.services.logic import get_promotion_count
from app.child.services.redirect import promote_to_next_round
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_t_db
from app.child.models.score import Score
from app.child.schemas.score import ScoreUpdate
from sqlalchemy import select, delete
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/{tournament_id}/kata", tags=["Kata"])

@router.patch("/save/{p_id}")
async def save_performance_score(
    p_id: int,
    data: ScoreUpdate,
    t_db: AsyncSession = Depends(get_t_db)
):
    # 1. Ищем запись выступления
    score_record = await t_db.get(Score, p_id)
    if not score_record:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    print(data)
    # 2. Собираем оценки в список для расчета
    all_scores = [data.s1, data.s2, data.s3, data.s4, data.s5]
    
    # Логика WKF (Ката): убираем 1 min и 1 max, суммируем остальные 3
    # Если судей 7, убирают 2 min и 2 max.
    sorted_scores = sorted(all_scores)
    final_sum = sum(sorted_scores[1:-1]) # Берем с 1-го по 3-й индекс (середина)

    # 3. Обновляем поля в БД
    score_record.performance_kata = data.performance_kata
    score_record.s1 = data.s1
    score_record.s2 = data.s2
    score_record.s3 = data.s3
    score_record.s4 = data.s4
    score_record.s5 = data.s5
    score_record.total_score = round(final_sum, 2)
    score_record.status = "finished"

    await t_db.commit()
    await t_db.refresh(score_record)

    return {
        "status": "success", 
        "total_score": score_record.total_score
    }

@router.post("/round/{round_id}/finish")
async def finish_round_complex(
    tournament_id: int,
    round_id: int,
    t_db: AsyncSession = Depends(get_t_db)
):
    # # 1. Загружаем данные
    # current_round = await t_db.get(Round, round_id)
    # res = await t_db.execute(select(Score).where(Score.round_id == round_id))
    # scores = res.scalars().all()
    
    # if not all(p.status == "finished" for p in scores):
    #     raise HTTPException(status_code=400, detail="Не все участники оценены")

    # # 2. Сортировка по WKF (Балл -> Min -> Max)
    # sorted_p = sort_performances_wkf(scores)
    
    # # 3. Определяем лимит прохода
    # limit = get_promotion_count(len(scores), current_round.round_number)
    
    # # 4. Проверка на абсолютное равенство на границе (Тай-брейк)
    # if len(sorted_p) > limit:
    #     p_last = sorted_p[limit-1] # Последний проходящий
    #     p_next = sorted_p[limit]   # Первый непроходящий
        
    #     # Если все критерии равны
    #     if (p_last.total_score == p_next.total_score and 
    #         sorted(p_last.scores_list)[0] == sorted(p_next.scores_list)[0] and
    #         sorted(p_last.scores_list)[-1] == sorted(p_next.scores_list)[-1]):
            
    #         return {
    #             "status": "tie", 
    #             "message": "Абсолютное равенство баллов! Назначьте доп. выступление для этих атлетов.",
    #             "athletes": [p_last.athlete_id, p_next.athlete_id]
    #         }

    # # 5. Создание следующего круга
    # next_round = Round(
    #     category_id=current_round.category_id,
    #     round_number=current_round.round_number + 1
    # )
    # t_db.add(next_round)
    # await t_db.flush()

    # for p in sorted_p[:limit]:
    #     t_db.add(Score(round_id=next_round.id, athlete_id=p.athlete_id))

    # current_round.is_finished = True
    # await t_db.commit()
    # return RedirectResponse(url=f"/view/{tournament_id}/kata", status_code=303)

    count = await promote_to_next_round(t_db, round_id)
    return {"status": "success", "promoted_count": count}