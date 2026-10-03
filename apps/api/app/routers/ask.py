"""Ask in plain English (masterplan 5.28): type a question, get an answer from the business's own figures with the numbers shown."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import ask, ask_llm, audit
from app.config import settings
from app.db import get_db
from app.deps import Principal, error, require_any
from app.models import AskQuestion

router = APIRouter(tags=["ask"])
PERMS = ("reports.view", "finance.view", "alerts.view")


class QuestionIn(BaseModel):
    question: str = Field(min_length=3, max_length=ask.MAX_QUESTION)


class LookupIn(BaseModel):
    lookup: str
    args: dict = Field(default_factory=dict)


def _tables(report: dict) -> dict:
    return {"title": report["title"], "from": report["from"], "to": report["to"], "notes": report["notes"], "sections": report["sections"]}


@router.post("/ask", status_code=status.HTTP_201_CREATED)
async def ask_question(body: QuestionIn, principal: Principal = Depends(require_any(*PERMS)), db: AsyncSession = Depends(get_db)):
    """Answers from the business's own data. The model may only call read-only lookups, run with this person's own permissions."""
    today = (await db.execute(select(func.count()).select_from(AskQuestion).where(AskQuestion.user_id == principal.user.id, AskQuestion.created_at >= datetime.now(UTC) - timedelta(days=1)))).scalar_one()
    if today >= settings.ask_per_day:
        raise error(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_questions", "That is a lot of questions for one day. Try the example questions, or ask again tomorrow.")
    try:
        result = await ask.answer(db, principal, body.question.strip())
    except ask_llm.AskError as e:
        raise error(status.HTTP_503_SERVICE_UNAVAILABLE, "ask_unavailable", str(e)) from None
    row = AskQuestion(user_id=principal.user.id, question=body.question.strip(), answer=result["answer"][:4000], lookups=result["lookups"], provider=result["provider"])
    db.add(row)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="ask.question", entity_type="ask_question", entity_id=row.id, after={"lookups": [x["lookup"] for x in result["lookups"]]})
    await db.commit()
    return {"id": row.id, **result}


@router.get("/ask/examples")
async def example_questions(principal: Principal = Depends(require_any(*PERMS))):
    """Questions that work without any AI: each runs a fixed lookup with the period filled in."""
    return ask.examples(principal)


@router.post("/ask/lookup")
async def run_lookup(body: LookupIn, principal: Principal = Depends(require_any(*PERMS)), db: AsyncSession = Depends(get_db)):
    """Runs one of the example lookups directly and returns its tables."""
    return _tables(await ask.lookup(db, principal, body.lookup, body.args))


@router.get("/ask/history")
async def my_history(principal: Principal = Depends(require_any(*PERMS)), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AskQuestion).where(AskQuestion.user_id == principal.user.id).order_by(AskQuestion.created_at.desc()).limit(30))).scalars().all()
    return [{"id": r.id, "question": r.question, "answer": r.answer, "lookups": r.lookups, "provider": r.provider, "created_at": r.created_at} for r in rows]

