from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


class TechStack(BaseModel):
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    databases: list[str] = Field(default_factory=list)
    infrastructure: list[str] = Field(default_factory=list)
    testing: list[str] = Field(default_factory=list)


class IdentifiedGap(BaseModel):
    area: str
    severity: Literal["high", "medium", "low"]
    description: str


class ProjectContext(BaseModel):
    project_summary: str
    tech_stack: TechStack
    identified_gaps: list[IdentifiedGap] = Field(default_factory=list)


class ContextItem(BaseModel):
    key: str
    display_name: str
    upload_id: str
    storage_path: Optional[str] = None
    excerpt: str


class DiscoveryQuestion(BaseModel):
    id: str
    question_text: str
    category: str
    priority: int = 1
    context_item_refs: list[str] = Field(default_factory=list)


class SessionConfig(BaseModel):
    max_duration_seconds: int = 300
    language: str = "en"
    voice_mode: str = "audio"
    agent_name: str = "Discovery"


class SupabaseCallback(BaseModel):
    url: str
    service_role_key: str
    voice_session_id: str


class VoiceSessionInitPayload(BaseModel):
    session_id: str
    user_id: str
    project_context_id: str
    model_provider: Literal["gemini", "openai", "dashscope"] = "gemini"
    session_config: SessionConfig = Field(default_factory=SessionConfig)
    project_context: ProjectContext
    context_items: list[ContextItem] = Field(default_factory=list)
    discovery_questions: list[DiscoveryQuestion] = Field(default_factory=list)
    supabase_callback: SupabaseCallback


class VoiceSessionCreatedResponse(BaseModel):
    session_id: str
    agentscope_session_id: str
    ws_endpoint: str
    status: str = "initializing"
    context_items_loaded: int = 0
    estimated_ready_in_ms: int = 2000
