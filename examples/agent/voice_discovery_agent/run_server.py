from __future__ import annotations
import asyncio
import json
import os
import traceback
import uuid
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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
from agent_pool import agent_pool
from analysis import analyze_project_explanation
import base64

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8002"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
PUBLIC_HOST = os.getenv("PUBLIC_HOST", f"localhost:{PORT}")
GEMINI_REALTIME_MODEL = os.getenv(
    "GEMINI_REALTIME_MODEL",
    "gemini-2.5-flash-native-audio-preview-09-2025",
)
OPENAI_REALTIME_MODEL = os.getenv(
    "OPENAI_REALTIME_MODEL",
    "gpt-4o-realtime-preview",
)
DASHSCOPE_REALTIME_MODEL = os.getenv(
    "DASHSCOPE_REALTIME_MODEL",
    "qwen3-omni-flash-realtime",
)


app = FastAPI(title="Voice Discovery Agent")

RECORDINGS_DIR = BASE_DIR / "recordings"
RECORDINGS_DIR.mkdir(exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    from session_store import DB_PATH
    import os
    from session_store import DB_PATH
    import os
    logger.info("Backend startup: CWD=%s | DB_PATH=%s", os.getcwd(), os.path.abspath(DB_PATH))
    logger.info("Backend starting up. Database path: %s", os.path.abspath(DB_PATH))
    async def create_agent():
        model = _create_realtime_model("gemini")
        agent = RealtimeAgent(
            name="Discovery",
            sys_prompt="You are a discovery assistant.",
            model=model,
            toolkit=None,
        )
        # We don't start the agent yet, just the model connection
        # Wait, RealtimeAgent.start() starts the model connect()
        # So we should call start with a dummy queue
        dummy_queue = asyncio.Queue()
        await agent.start(dummy_queue)
        return agent

    # Pre-warm 2 agents
    asyncio.create_task(agent_pool.fill(create_agent, 2))


def _check_internal_key(key: str | None) -> None:
    if INTERNAL_SERVICE_KEY and key != INTERNAL_SERVICE_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


def _is_configured_secret(value: str | None) -> bool:
    cleaned = (value or "").strip()
    if not cleaned:
        return False
    return not (
        cleaned.startswith("your_")
        or cleaned.endswith("_api_key")
        or cleaned in {"changeme", "change-me", "test-key"}
    )


def _provider_availability() -> dict[str, bool]:
    return {
        "dashscope": _is_configured_secret(DASHSCOPE_API_KEY),
        "gemini": _is_configured_secret(GEMINI_API_KEY),
        "openai": _is_configured_secret(OPENAI_API_KEY),
    }


def _create_realtime_model(model_provider: str):
    availability = _provider_availability()
    if model_provider not in availability:
        raise ValueError(f"Unsupported model provider: {model_provider}")
    if not availability[model_provider]:
        env_name = f"{model_provider.upper()}_API_KEY"
        raise RuntimeError(
            f"{env_name} is missing or still set to a placeholder. "
            "Configure it in .env or the process environment before starting voice chat."
        )

    if model_provider == "dashscope":
        return DashScopeRealtimeModel(
            model_name=DASHSCOPE_REALTIME_MODEL,
            api_key=DASHSCOPE_API_KEY,
        )
    if model_provider == "openai":
        return OpenAIRealtimeModel(
            model_name=OPENAI_REALTIME_MODEL,
            api_key=OPENAI_API_KEY,
        )
    return GeminiRealtimeModel(
        model_name=GEMINI_REALTIME_MODEL,
        api_key=GEMINI_API_KEY,
    )


async def _send_agent_error(
    websocket: WebSocket,
    message: str,
    *,
    error_type: str = "voice_agent_error",
    code: str = "VOICE_AGENT_ERROR",
    agent_name: str = "VoiceAgent",
) -> None:
    await websocket.send_json(
        {
            "type": "agent_error",
            "error_type": error_type,
            "code": code,
            "message": message,
            "agent_id": "",
            "agent_name": agent_name,
        }
    )


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

            logger.info("Backend event received: session=%s type=%s", session_id, event_type)
            
            if event_type == "agent_response_audio_delta":
                logger.info(
                    "TTS audio chunk generated: session=%s agent=%s b64_len=%s",
                    session_id,
                    event_dict.get("agent_name"),
                    len(event_dict.get("delta", "")),
                )
            
            if event_type == "agent_response_audio_transcript_delta":
                logger.info(
                    "Agent response transcript delta: session=%s delta=%s",
                    session_id,
                    event_dict.get("delta"),
                )
                delta = event_dict.get("delta", "")
                if delta:
                    agent_text_buffer.append(delta)
            
            elif event_type == "agent_response_audio_transcript_done":
                text = "".join(agent_text_buffer).strip()
                agent_text_buffer.clear()
                if text:
                    store.append_transcript_turn(
                        session_id, turn_counter[0], "agent", text, [], "question"
                    )
                    turn_counter[0] += 1
            
            if event_type == "agent_error":
                logger.error("Agent error: session=%s message=%s", session_id, event_dict.get("message"))

            # User speech transcribed
            elif event_type == "agent_input_transcription_done":
                transcript = (
                    event_dict.get("transcript", "")
                    or event_dict.get("text", "")
                )
                if transcript:
                    logger.info(
                        "Transcription generated: session=%s transcript=%s",
                        session_id,
                        transcript,
                    )
                    store.append_transcript_turn(
                        session_id, turn_counter[0], "user", transcript, [], "answer"
                    )
                    turn_counter[0] += 1

            elif event_type == "agent_response_done":
                logger.info("Agent response generated: session=%s", session_id)

            await websocket.send_json(event_dict)

    except Exception as e:
        logger.warning(f"[_capturing_frontend_receive] error: {e}")


# ─── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/")
async def index() -> FileResponse:
    logger.info("Serving voice demo page: /")
    return FileResponse(BASE_DIR / "test.html")


@app.get("/test.html")
async def test_page() -> FileResponse:
    logger.info("Serving voice demo page: /test.html")
    return FileResponse(BASE_DIR / "test.html")


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "providers": _provider_availability(),
        "pool": agent_pool.stats(),
    }


@app.get("/api/check-models")
async def check_models() -> dict[str, bool]:
    availability = _provider_availability()
    logger.info("Model availability checked: %s", availability)
    return availability


@app.post("/sessions", status_code=201, response_model=VoiceSessionCreatedResponse)
async def create_session(
    payload: VoiceSessionInitPayload,
    x_internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
) -> VoiceSessionCreatedResponse:
    logger.info(
        "[REST SESSION] Create requested: session=%s user=%s model_provider=%s",
        payload.session_id,
        payload.user_id,
        payload.model_provider,
    )
    _check_internal_key(x_internal_secret)
    store.upsert_session(payload.session_id, payload.model_dump())
    store.set_status(payload.session_id, "initializing")

    # Build system prompt in background so HTTP response returns immediately
    asyncio.create_task(_initialize_context(payload))

    protocol = "ws" if "localhost" in PUBLIC_HOST or "127.0.0.1" in PUBLIC_HOST else "wss"
    ws_endpoint = f"{protocol}://{PUBLIC_HOST}/ws/{payload.user_id}/{payload.session_id}"
    return VoiceSessionCreatedResponse(
        session_id=payload.session_id,
        # Echo the stored session_id so the frontend's ws_endpoint and agentscopeSessionId
        # both resolve to the same DB key.  The old str(uuid.uuid4()) was never stored.
        agentscope_session_id=payload.session_id,
        ws_endpoint=ws_endpoint,
        context_items_loaded=len(payload.context_items),
    )


@app.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    row = store.get_session(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    
    protocol = "ws" if "localhost" in PUBLIC_HOST or "127.0.0.1" in PUBLIC_HOST else "wss"
    ws_endpoint = f"{protocol}://{PUBLIC_HOST}/ws/{row.user_id}/{session_id}"
    
    return {
        "session_id": session_id, 
        "status": row.status,
        "ws_endpoint": ws_endpoint
    }

@app.get("/debug/db")
async def debug_db():
    from session_store import SessionLocal, DiscoverySessionRow
    with SessionLocal() as db:
        rows = db.query(DiscoverySessionRow).all()
        return [
            {
                "session_id": r.session_id,
                "user_id": r.user_id,
                "voice_session_id": r.voice_session_id,
                "status": r.status
            }
            for r in rows
        ]


@app.delete("/sessions/{session_id}", status_code=204)
async def end_session(
    session_id: str,
    x_internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
) -> None:
    _check_internal_key(x_internal_secret)
    logger.info("REST session delete requested: session=%s", session_id)
    row = store.get_session(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    await flush_transcript_to_supabase(session_id)
    store.delete_transcript(session_id)
    store.delete_session(session_id)


# ─── Background: build system prompt ──────────────────────────────────────────

async def _initialize_context(payload: VoiceSessionInitPayload) -> None:
    try:
        logger.info(
            "Context initialization started: session=%s context_items=%s",
            payload.session_id,
            len(payload.context_items),
        )
        context_texts = await load_context_texts(
            payload.context_items,
            payload.supabase_callback.url,
            payload.supabase_callback.service_role_key,
        )
        sys_prompt = build_system_prompt(payload, context_texts)
        
        # Acquire agent from pool and pre-configure it
        agent = await agent_pool.acquire(payload.session_id)
        if agent:
            logger.info("Specializing pooled agent for session: %s", payload.session_id)
            await agent.model.update_instructions(sys_prompt)
            agent.sys_prompt = sys_prompt

        row = store.get_session(payload.session_id)
        if row:
            p = json.loads(row.payload_json)
            p["_sys_prompt"] = sys_prompt
            store.upsert_session(payload.session_id, p)
        store.set_status(payload.session_id, "ready")
        logger.info("Context initialization ready: session=%s", payload.session_id)
    except Exception as e:
        store.set_status(payload.session_id, "failed")
        logger.error("Context initialization failed: session=%s error=%s", payload.session_id, e)
        await mark_session_failed(payload.session_id, str(e))


# ─── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws/{user_id}/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket, user_id: str, session_id: str
) -> None:
    await websocket.accept()
    logger.info("[WS HANDSHAKE] Connection attempt: user=%s session=%s", user_id, session_id)

    # Wait up to 10 s for context initialization (Frontend timeout is 15s)
    POLL_INTERVAL = 0.5
    MAX_POLLS = 20  # 20 × 0.5 s = 10 s
    row = None
    found_in_db = False
    
    for i in range(MAX_POLLS):
        row = store.get_session(session_id)
        if row and row.status in ["ready", "initializing"]:
            found_in_db = True
            logger.info(
                "[WS HANDSHAKE] Session found in DB: session=%s status=%s (attempt %d/%d)",
                session_id,
                row.status,
                i + 1,
                MAX_POLLS
            )
            break
        
        if row and row.status == "failed":
            logger.error("[WS HANDSHAKE] Session %s failed initialization", session_id)
            try:
                await websocket.send_json({"type": "error", "message": "Session context initialization failed"})
                await websocket.close()
            except Exception: pass
            return

        if i % 5 == 0:
            logger.info("[WS HANDSHAKE] Polling for session... attempt %d/%d", i+1, MAX_POLLS)
            
        await asyncio.sleep(POLL_INTERVAL)
    
    if not found_in_db:
        from session_store import DB_PATH
        import os
        error_reason = (
            f"Session '{session_id}' not found in backend database after {MAX_POLLS} polls. "
            "Ensure POST /sessions was called on this backend instance."
        )
        logger.error(
            "[WS REJECT] Code 1008: session_not_found | session=%s | user=%s | db=%s | origin=%s",
            session_id,
            user_id,
            os.path.abspath(DB_PATH),
            websocket.headers.get("origin", "none"),
        )
        try:
            await websocket.send_json({
                "type": "error",
                "message": error_reason,
            })
            await websocket.close(code=1008, reason=error_reason[:120])
        except Exception as exc:
            logger.error("Failed to send error or close WS: %s", exc)
        return

    row = store.get_session(session_id)
    if not row:
        await websocket.close()
        return
    if row.user_id != user_id:
        error_reason = f"User mismatch: path_user={user_id} stored_user={row.user_id}"
        logger.error(
            "WS REJECT [1008]: user_mismatch | session=%s | path_user=%s | stored_user=%s | origin=%s",
            session_id,
            user_id,
            row.user_id,
            websocket.headers.get("origin", "none"),
        )
        await _send_agent_error(
            websocket,
            "The WebSocket user route does not match the stored session owner.",
            error_type="authorization_error",
            code="SESSION_USER_MISMATCH",
        )
        await websocket.close(code=1008, reason=error_reason[:120])
        return

    payload_dict = json.loads(row.payload_json)
    sys_prompt = payload_dict.get("_sys_prompt", "You are a discovery assistant.")

    turn_counter: list[int] = [0]
    agent_text_buffer: list[str] = []
    audio_chunk_count = 0

    # One queue per session — agent writes ServerEvents, we read and forward
    frontend_queue: asyncio.Queue = asyncio.Queue()
    asyncio.create_task(
        _capturing_frontend_receive(
            websocket, frontend_queue, session_id, turn_counter, agent_text_buffer
        )
    )

    agent = None
    pooled_agent = False
    client_requested_end = False
    disconnected_unexpectedly = False

    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("type")
            logger.info("WebSocket message received: session=%s type=%s", session_id, event_type)
            client_event = ClientEvents.from_json(data)

            if isinstance(client_event, ClientEvents.ClientSessionCreateEvent):
                client_config = client_event.config or {}
                model_provider = client_config.get("model_provider") or row.model_provider
                agent_name = (
                    client_config.get("agent_name")
                    or payload_dict.get("session_config", {}).get("agent_name")
                    or "Discovery"
                )
                agent_instructions = client_config.get("instructions") or sys_prompt

                logger.info(
                    "Voice agent session create received: session=%s provider=%s agent=%s",
                    session_id,
                    model_provider,
                    agent_name,
                )

                # Try to get the agent assigned during initialization
                agent = agent_pool.active_agents.get(session_id)
                pooled_agent = agent is not None
                
                if not agent:
                    logger.info("No pooled agent found for session %s, creating one-off cold fallback", session_id)
                    try:
                        model = _create_realtime_model(model_provider)
                        agent = RealtimeAgent(
                            name=agent_name,
                            sys_prompt=agent_instructions,
                            model=model,
                            toolkit=None,
                        )
                        await agent.start(frontend_queue)
                    except Exception as error:
                        # ... error handling ...
                        message = str(error)
                        await _send_agent_error(websocket, message, error_type="configuration_error", code="VOICE_AGENT_CONFIGURATION_ERROR", agent_name=agent_name)
                        await websocket.close()
                        break
                else:
                    logger.info("Using pre-warmed agent for session: %s", session_id)
                    logger.debug("Updating agent instructions (len=%d)", len(agent_instructions))
                    try:
                        await agent.model.update_instructions(agent_instructions)
                    except Exception as e:
                        logger.error("Failed to update instructions: %s", e)
                        raise
                    await agent.attach_output_queue(frontend_queue)

                logger.info("Voice agent active: session=%s provider=%s", session_id, model_provider)

                store.set_status(session_id, "active")
                await websocket.send_json(
                    ServerEvents.ServerSessionCreatedEvent(
                        session_id=session_id,
                    ).model_dump()
                )

                # PROACTIVE GREETING: If in practice mode, trigger the agent to speak immediately
                if payload_dict.get("session_config", {}).get("mode") == "practice":
                    logger.info("Triggering proactive greeting for practice session: %s", session_id)
                    # Use the specific kickoff text from the prompt
                    greeting_trigger = f"Hi {payload_dict.get('user_name', 'User')}, please start the session."
                    await agent.handle_input(ClientEvents.ClientTextAppendEvent(text=greeting_trigger))

            elif client_event.type == ClientEventType.CLIENT_SESSION_END:
                logger.info("Client requested session end: session=%s", session_id)
                client_requested_end = True
                break

            else:
                if agent:
                    if isinstance(client_event, ClientEvents.ClientAudioAppendEvent):
                        audio_chunk_count += 1
                        if audio_chunk_count == 1 or audio_chunk_count % 25 == 0:
                            logger.info(
                                "Audio chunk received by backend: session=%s chunk=%s b64_len=%s",
                                session_id,
                                audio_chunk_count,
                                len(client_event.audio),
                            )
                    elif isinstance(client_event, ClientEvents.ClientTextAppendEvent):
                        logger.info(
                            "Text input received by backend: session=%s chars=%s",
                            session_id,
                            len(client_event.text),
                        )
                    
                    # Record user audio to file
                    if isinstance(client_event, ClientEvents.ClientAudioAppendEvent):
                        audio_path = RECORDINGS_DIR / f"{session_id}.pcm"
                        with open(audio_path, "ab") as f:
                            f.write(base64.b64decode(client_event.audio))
                        store.set_recording_path(session_id, str(audio_path))

                    await agent.handle_input(client_event)
                else:
                    logger.warning(
                        "Ignoring client event before agent is ready: session=%s type=%s",
                        session_id,
                        event_type,
                    )

    except WebSocketDisconnect:
        disconnected_unexpectedly = not client_requested_end
        logger.info("WebSocket disconnected: user=%s session=%s", user_id, session_id)
    except Exception as e:
        logger.warning("WS session %s error: %s", session_id, e)
        traceback.print_exc()
        await mark_session_failed(session_id, str(e))
    finally:
        # Run analysis if in practice mode
        if not disconnected_unexpectedly and payload_dict.get("session_config", {}).get("mode") == "practice":
            logger.info("Session ended. Starting post-session analysis: %s", session_id)
            feedback = await analyze_project_explanation(session_id)
            store.set_feedback(session_id, feedback)
            logger.info("Analysis complete for session %s", session_id)

        if agent:
            if pooled_agent:
                await agent_pool.discard(session_id)
            else:
                try:
                    await agent.stop()
                except Exception as exc:
                    logger.warning("Failed to stop cold agent for session=%s error=%s", session_id, exc)

        if disconnected_unexpectedly:
            store.set_status(session_id, "ready")
            logger.info("Preserved session for reconnect: session=%s", session_id)
            return

        store.set_status(session_id, "ended")
        await flush_transcript_to_supabase(session_id)
        store.delete_transcript(session_id)
        store.delete_session(session_id)


if __name__ == "__main__":
    uvicorn.run("run_server:app", host=HOST, port=PORT, reload=False)
