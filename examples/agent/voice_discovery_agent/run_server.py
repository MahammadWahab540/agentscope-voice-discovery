from __future__ import annotations
import asyncio
import json
import os
import traceback
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import JSONResponse

from agentscope import logger
from agentscope.agent import RealtimeAgent
from agentscope.realtime import (
    DashScopeRealtimeModel,
    GeminiRealtimeModel,
    OpenAIRealtimeModel,
    ClientEvents,
    ServerEvents,
    ClientEventType,
)

from context_loader import load_context_texts
from models import VoiceSessionCreatedResponse, VoiceSessionInitPayload
from session_store import store
from supabase_callback import flush_transcript_to_supabase, mark_session_failed
from system_prompt_builder import build_system_prompt

INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8001"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
PUBLIC_HOST = os.getenv("PUBLIC_HOST", f"localhost:{PORT}")


app = FastAPI(title="Voice Discovery Agent")


def _check_internal_key(key: str | None) -> None:
    if INTERNAL_SERVICE_KEY and key != INTERNAL_SERVICE_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


async def _capturing_frontend_receive(
    websocket: WebSocket,
    frontend_queue: asyncio.Queue,
    session_id: str,
    turn_counter: list[int],
    agent_text_buffer: list[str],
) -> None:
    """Forward ServerEvents to the frontend WebSocket while capturing transcript turns."""
    try:
        while True:
            msg: ServerEvents.EventBase = await frontend_queue.get()
            event_dict = msg.model_dump()
            event_type = event_dict.get("type", "")

            # Capture agent speech deltas
            if event_type == "response.audio_transcript.delta":
                delta = event_dict.get("delta", "")
                if delta:
                    agent_text_buffer.append(delta)

            # Agent turn complete — flush buffer to SQLite
            elif event_type == "response.audio_transcript.done":
                text = "".join(agent_text_buffer).strip()
                agent_text_buffer.clear()
                if text:
                    store.append_transcript_turn(
                        session_id, turn_counter[0], "agent", text, [], "question"
                    )
                    turn_counter[0] += 1

            # User speech transcribed
            elif event_type in (
                "conversation.item.input_audio_transcription.completed",
                "input_audio_buffer.speech_stopped",
            ):
                transcript = (
                    event_dict.get("transcript", "")
                    or event_dict.get("text", "")
                )
                if transcript:
                    store.append_transcript_turn(
                        session_id, turn_counter[0], "user", transcript, [], "answer"
                    )
                    turn_counter[0] += 1

            await websocket.send_json(event_dict)

    except Exception as e:
        logger.warning(f"[_capturing_frontend_receive] error: {e}")


# ─── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/sessions", status_code=201, response_model=VoiceSessionCreatedResponse)
async def create_session(
    payload: VoiceSessionInitPayload,
    x_internal_secret: str | None = None,
) -> VoiceSessionCreatedResponse:
    _check_internal_key(x_internal_secret)

    store.upsert_session(payload.session_id, payload.model_dump())
    store.set_status(payload.session_id, "initializing")

    # Build system prompt in background so HTTP response returns immediately
    asyncio.create_task(_initialize_context(payload))

    ws_endpoint = f"wss://{PUBLIC_HOST}/ws/{payload.user_id}/{payload.session_id}"
    return VoiceSessionCreatedResponse(
        session_id=payload.session_id,
        agentscope_session_id=str(uuid.uuid4()),
        ws_endpoint=ws_endpoint,
        context_items_loaded=len(payload.context_items),
    )


@app.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    row = store.get_session(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "status": row.status}


@app.delete("/sessions/{session_id}", status_code=204)
async def end_session(
    session_id: str, x_internal_secret: str | None = None
) -> None:
    _check_internal_key(x_internal_secret)
    row = store.get_session(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    await flush_transcript_to_supabase(session_id)
    store.delete_transcript(session_id)
    store.delete_session(session_id)


# ─── Background: build system prompt ──────────────────────────────────────────

async def _initialize_context(payload: VoiceSessionInitPayload) -> None:
    try:
        context_texts = await load_context_texts(
            payload.context_items,
            payload.supabase_callback.url,
            payload.supabase_callback.service_role_key,
        )
        sys_prompt = build_system_prompt(payload, context_texts)
        row = store.get_session(payload.session_id)
        if row:
            p = json.loads(row.payload_json)
            p["_sys_prompt"] = sys_prompt
            store.upsert_session(payload.session_id, p)
        store.set_status(payload.session_id, "ready")
    except Exception as e:
        store.set_status(payload.session_id, "failed")
        await mark_session_failed(payload.session_id, str(e))


# ─── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws/{user_id}/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket, user_id: str, session_id: str
) -> None:
    await websocket.accept()
    logger.info("WS connected: user=%s session=%s", user_id, session_id)

    # Wait up to 10 s for context initialization
    for _ in range(20):
        row = store.get_session(session_id)
        if row and row.status == "ready":
            break
        await asyncio.sleep(0.5)
    else:
        await websocket.send_json(
            {"type": "error", "message": "Session initialization timed out"}
        )
        await websocket.close()
        return

    row = store.get_session(session_id)
    if not row:
        await websocket.close()
        return

    payload_dict = json.loads(row.payload_json)
    sys_prompt = payload_dict.get("_sys_prompt", "You are a discovery assistant.")
    model_provider = row.model_provider

    turn_counter: list[int] = [0]
    agent_text_buffer: list[str] = []

    # One queue per session — agent writes ServerEvents, we read and forward
    frontend_queue: asyncio.Queue = asyncio.Queue()
    asyncio.create_task(
        _capturing_frontend_receive(
            websocket, frontend_queue, session_id, turn_counter, agent_text_buffer
        )
    )

    agent = None

    try:
        while True:
            data = await websocket.receive_json()
            client_event = ClientEvents.from_json(data)

            if isinstance(client_event, ClientEvents.ClientSessionCreateEvent):
                # Create the model and agent on first CLIENT_SESSION_CREATE
                if model_provider == "dashscope":
                    model = DashScopeRealtimeModel(
                        model_name="qwen3-omni-flash-realtime",
                        api_key=DASHSCOPE_API_KEY,
                    )
                elif model_provider == "openai":
                    model = OpenAIRealtimeModel(
                        model_name="gpt-4o-realtime-preview",
                        api_key=OPENAI_API_KEY,
                    )
                else:
                    # Default to Gemini
                    model = GeminiRealtimeModel(
                        model_name="gemini-2.5-flash-native-audio-preview-09-2025",
                        api_key=GEMINI_API_KEY,
                    )

                agent_name = payload_dict.get("session_config", {}).get(
                    "agent_name", "Discovery"
                )
                agent = RealtimeAgent(
                    name=agent_name,
                    sys_prompt=sys_prompt,
                    model=model,
                    toolkit=None,
                )
                await agent.start(frontend_queue)

                store.set_status(session_id, "active")
                await websocket.send_json(
                    ServerEvents.ServerSessionCreatedEvent(
                        session_id=session_id,
                    ).model_dump()
                )

            elif client_event.type == ClientEventType.CLIENT_SESSION_END:
                if agent:
                    await agent.stop()
                    agent = None
                break

            else:
                if agent:
                    await agent.handle_input(client_event)

    except Exception as e:
        logger.warning("WS session %s error: %s", session_id, e)
        traceback.print_exc()
        await mark_session_failed(session_id, str(e))
    finally:
        store.set_status(session_id, "ended")
        await flush_transcript_to_supabase(session_id)
        store.delete_transcript(session_id)
        store.delete_session(session_id)


if __name__ == "__main__":
    uvicorn.run("run_server:app", host=HOST, port=PORT, reload=False)
