from __future__ import annotations
import json
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("SQLITE_DB_PATH", str(BASE_DIR / "voice_discovery.db"))
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class DiscoverySessionRow(Base):
    __tablename__ = "discovery_sessions"
    session_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    project_context_id = Column(String, nullable=False)
    voice_session_id = Column(String, nullable=False)
    model_provider = Column(String, default="gemini")
    status = Column(String, default="initializing")
    payload_json = Column(Text, nullable=False)
    supabase_url = Column(String, nullable=False)
    supabase_key = Column(String, nullable=False)
    feedback = Column(Text, nullable=True)
    recording_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TranscriptRow(Base):
    __tablename__ = "transcript_buffer"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False, index=True)
    turn_index = Column(Integer, nullable=False)
    speaker = Column(String, nullable=False)
    content_text = Column(Text, nullable=False)
    context_items_used = Column(Text, default="[]")
    turn_type = Column(String, default="conversation")
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(engine)


class SessionStore:
    def upsert_session(self, session_id: str, payload_dict: dict) -> None:
        with SessionLocal() as db:
            row = db.get(DiscoverySessionRow, session_id)
            p = payload_dict
            if row is None:
                from agentscope import logger
                logger.info("SQLITE: Creating new session record: id=%s user=%s voice_id=%s", session_id, p["user_id"], p["supabase_callback"]["voice_session_id"])
                row = DiscoverySessionRow(
                    session_id=session_id,
                    user_id=p["user_id"],
                    project_context_id=p["project_context_id"],
                    voice_session_id=p["supabase_callback"]["voice_session_id"],
                    model_provider=p.get("model_provider", "gemini"),
                    status="initializing",
                    payload_json=json.dumps(p),
                    supabase_url=p["supabase_callback"]["url"],
                    supabase_key=p["supabase_callback"]["service_role_key"],
                )
                db.add(row)
            else:
                from agentscope import logger
                logger.info("SQLITE: Updating existing session record: id=%s", session_id)
                row.payload_json = json.dumps(p)
            db.commit()

    def set_status(self, session_id: str, status: str) -> None:
        with SessionLocal() as db:
            row = db.get(DiscoverySessionRow, session_id)
            if row:
                row.status = status
                db.commit()

    def get_session(self, session_id: str) -> Optional[DiscoverySessionRow]:
        with SessionLocal() as db:
            row = db.get(DiscoverySessionRow, session_id)
            if not row:
                from agentscope import logger
                logger.warning("SQLITE: Session not found: id=%s", session_id)
            return row

    def delete_session(self, session_id: str) -> None:
        with SessionLocal() as db:
            row = db.get(DiscoverySessionRow, session_id)
            if row:
                db.delete(row)
                db.commit()

    def append_transcript_turn(
        self,
        session_id: str,
        turn_index: int,
        speaker: str,
        content_text: str,
        context_items_used: list[str],
        turn_type: str = "conversation",
    ) -> None:
        with SessionLocal() as db:
            db.add(
                TranscriptRow(
                    session_id=session_id,
                    turn_index=turn_index,
                    speaker=speaker,
                    content_text=content_text,
                    context_items_used=json.dumps(context_items_used),
                    turn_type=turn_type,
                )
            )
            db.commit()

    def get_transcript(self, session_id: str) -> list[dict]:
        with SessionLocal() as db:
            rows = (
                db.query(TranscriptRow)
                .filter(TranscriptRow.session_id == session_id)
                .order_by(TranscriptRow.turn_index)
                .all()
            )
            return [
                {
                    "turn_index": r.turn_index,
                    "speaker": r.speaker,
                    "content_text": r.content_text,
                    "context_items_used": json.loads(r.context_items_used),
                    "turn_type": r.turn_type,
                }
                for r in rows
            ]

    def set_feedback(self, session_id: str, feedback: str) -> None:
        with SessionLocal() as db:
            row = db.get(DiscoverySessionRow, session_id)
            if row:
                row.feedback = feedback
                db.commit()

    def set_recording_path(self, session_id: str, path: str) -> None:
        with SessionLocal() as db:
            row = db.get(DiscoverySessionRow, session_id)
            if row:
                row.recording_path = path
                db.commit()

    def delete_transcript(self, session_id: str) -> None:
        with SessionLocal() as db:
            db.query(TranscriptRow).filter(
                TranscriptRow.session_id == session_id
            ).delete()
            db.commit()


store = SessionStore()
