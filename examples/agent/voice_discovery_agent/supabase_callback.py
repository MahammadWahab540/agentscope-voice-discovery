from __future__ import annotations
import httpx
from datetime import datetime, timezone
from session_store import store


async def flush_transcript_to_supabase(session_id: str) -> bool:
    row = store.get_session(session_id)
    if not row:
        return False

    transcript = store.get_transcript(session_id)
    if not transcript:
        return True

    supa_url = row.supabase_url
    supa_key = row.supabase_key
    voice_session_id = row.voice_session_id
    user_id = row.user_id

    rows = [
        {
            "voice_session_id": voice_session_id,
            "user_id": user_id,
            "turn_index": t["turn_index"],
            "speaker": t["speaker"],
            "content_text": t["content_text"],
            "context_items_used": t["context_items_used"],
            "turn_type": t["turn_type"],
        }
        for t in transcript
    ]

    headers = {
        "apikey": supa_key,
        "Authorization": f"Bearer {supa_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{supa_url}/rest/v1/voice_transcripts", json=rows, headers=headers
            )
            resp.raise_for_status()

            ended_at = datetime.now(timezone.utc).isoformat()
            await client.patch(
                f"{supa_url}/rest/v1/voice_sessions?id=eq.{voice_session_id}",
                json={
                    "status": "ended",
                    "ended_at": ended_at,
                    "transcript_saved": True,
                    "question_count": sum(
                        1 for t in transcript if t["speaker"] == "agent"
                    ),
                    "updated_at": ended_at,
                },
                headers=headers,
            )
        return True
    except httpx.HTTPError as e:
        print(f"[supabase_callback] flush failed: {e}")
        return False


async def mark_session_failed(session_id: str, error: str) -> None:
    row = store.get_session(session_id)
    if not row:
        return
    headers = {
        "apikey": row.supabase_key,
        "Authorization": f"Bearer {row.supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.patch(
                f"{row.supabase_url}/rest/v1/voice_sessions?id=eq.{row.voice_session_id}",
                json={"status": "failed", "error_message": error[:500]},
                headers=headers,
            )
    except Exception:
        pass
