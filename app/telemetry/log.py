"""
The question log: one row per question asked (app/db/app_tables.py `questions`), plus upload events.

    log = QuestionLog(owner_engine, prices)
    qid = log.record(result, identity=..., conversation_id=..., dataset_id=..., ...)
    log.history(conversation_id, identity)      # previous turns, for follow-up questions
    log.get(qid, identity)                      # None unless this identity asked it
    log.set_feedback(qid, identity, rating, note)
    log.record_upload(user_id, {...})

Writing the log never breaks answering: errors are logged and swallowed by the caller.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, and_, func, insert, select, update

from app.accounts.sessions import Identity
from app.db.app_tables import questions, usage_events
from app.telemetry.pricing import estimate_cost_usd

HISTORY_TURNS = 3  # previous turns given to the model for a follow-up question
ANSWER_CHARS = 400  # how much of each previous answer is included


@dataclass(frozen=True)
class StoredQuestion:
    id: str
    conversation_id: str
    dataset_id: str
    question: str
    standalone_question: str
    sql: str
    answer: str
    status: str
    sql_model: str
    summary_model: str
    latency_ms: int
    created_at: Any


def _owner_filter(identity: Identity):
    if identity.user_id:
        return questions.c.user_id == identity.user_id
    return and_(questions.c.guest_id == identity.guest_id, questions.c.user_id.is_(None))


def _step_ms(trace: list[dict], name: str) -> int:
    return sum(s.get("ms", 0) for s in trace if s.get("step") == name)


class QuestionLog:
    def __init__(self, engine: Engine, prices: dict[str, tuple[float, float]]):
        self.engine = engine
        self.prices = prices

    # ---- write ---------------------------------------------------------------------------------
    def record(
        self,
        result: dict[str, Any],
        *,
        identity: Identity,
        conversation_id: str,
        turn: int,
        dataset_id: str,
        dataset_kind: str,
        models: dict[str, str],
    ) -> tuple[str, float | None]:
        """Store one answered question; returns (question id, estimated cost in USD)."""
        trace = result.get("trace", [])
        cost = estimate_cost_usd(trace, self.prices)
        qid = uuid.uuid4().hex
        values = {
            "id": qid,
            "user_id": identity.user_id,
            "guest_id": None if identity.user_id else identity.guest_id,
            "conversation_id": conversation_id,
            "turn": turn,
            "dataset_id": dataset_id,
            "dataset_kind": dataset_kind,
            "question": result["question"],
            "standalone_question": result.get("standalone_question", ""),
            "sql": result.get("sql", ""),
            "answer": result.get("answer", ""),
            "status": result["status"],
            "attempts": result.get("attempts", 0),
            "rows": len(result.get("rows", [])),
            "chart": (result.get("chart") or {}).get("type", ""),
            "latency_ms": result.get("latency_ms", 0),
            "sql_ms": _step_ms(trace, "generate_sql"),
            "validate_ms": _step_ms(trace, "validate"),
            "execute_ms": _step_ms(trace, "execute"),
            "summary_ms": _step_ms(trace, "summarize"),
            "provider": models.get("provider", ""),
            "sql_model": models.get("sql_model", ""),
            "summary_model": models.get("summary_model", ""),
            "input_tokens": result.get("usage", {}).get("input_tokens", 0),
            "output_tokens": result.get("usage", {}).get("output_tokens", 0),
            "cost_usd": cost,
            "is_follow_up": turn > 1,
        }
        with self.engine.begin() as conn:
            conn.execute(insert(questions).values(**values))
        return qid, cost

    def record_upload(self, user_id: str | None, data: dict[str, Any]) -> None:
        with self.engine.begin() as conn:
            conn.execute(insert(usage_events).values(kind="upload", user_id=user_id, data=data))

    def set_feedback(self, qid: str, identity: Identity, rating: int, note: str = "") -> bool:
        with self.engine.begin() as conn:
            res = conn.execute(
                update(questions)
                .where(questions.c.id == qid, _owner_filter(identity))
                .values(feedback=rating or None, feedback_note=note[:1000])
            )
        return res.rowcount > 0

    def adopt_guest(self, guest_id: str, user_id: str) -> None:
        """After sign-in, the guest's earlier questions (and their follow-ups) belong to the user."""
        with self.engine.begin() as conn:
            conn.execute(
                update(questions)
                .where(questions.c.guest_id == guest_id, questions.c.user_id.is_(None))
                .values(user_id=user_id)
            )

    # ---- read ----------------------------------------------------------------------------------
    def get(self, qid: str, identity: Identity) -> StoredQuestion | None:
        cols = [questions.c[f] for f in StoredQuestion.__dataclass_fields__]
        with self.engine.connect() as conn:
            row = conn.execute(select(*cols).where(questions.c.id == qid, _owner_filter(identity))).first()
        return StoredQuestion(*row) if row else None

    def history(self, conversation_id: str, identity: Identity, dataset_id: str) -> list[dict[str, str]]:
        """Previous answered turns of this conversation (oldest first), for follow-up questions."""
        query = (
            select(questions.c.question, questions.c.standalone_question, questions.c.sql, questions.c.answer)
            .where(
                questions.c.conversation_id == conversation_id,
                questions.c.dataset_id == dataset_id,
                questions.c.status == "ok",
                _owner_filter(identity),
            )
            .order_by(questions.c.created_at.desc(), questions.c.turn.desc())
            .limit(HISTORY_TURNS)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(query).all()
        return [
            {"question": r.standalone_question or r.question, "sql": r.sql, "answer": r.answer[:ANSWER_CHARS]}
            for r in reversed(rows)
        ]

    def turns(self, conversation_id: str, identity: Identity) -> int:
        with self.engine.connect() as conn:
            return conn.execute(
                select(func.count()).where(questions.c.conversation_id == conversation_id, _owner_filter(identity))
            ).scalar_one()
