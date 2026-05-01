from __future__ import annotations
from models import VoiceSessionInitPayload


def build_system_prompt(
    payload: VoiceSessionInitPayload, context_texts: dict[str, str]
) -> str:
    pc = payload.project_context
    cfg = payload.session_config

    lines = [
        f"You are {cfg.agent_name}, a senior technical architect conducting a focused "
        f"discovery session. You have reviewed the project materials listed below. "
        f"Ask {len(payload.discovery_questions)} targeted questions to clarify missing details.",
        "",
        "RULES:",
        "- Ask ONE question at a time and wait for the user's answer.",
        "- Keep the entire session under 5 minutes.",
        "- Never ask about things already documented in the uploaded materials.",
        "- When referencing a document, prefix it with its @context key (e.g. '@context:readme').",
        "- Be direct and technical. No filler.",
        "",
        "## Project Summary",
        pc.project_summary,
        "",
        "## Detected Tech Stack",
        f"- Languages: {', '.join(pc.tech_stack.languages) or 'Unknown'}",
        f"- Frameworks: {', '.join(pc.tech_stack.frameworks) or 'Unknown'}",
        f"- Databases: {', '.join(pc.tech_stack.databases) or 'Unknown'}",
        f"- Infrastructure: {', '.join(pc.tech_stack.infrastructure) or 'Unknown'}",
        "",
    ]

    if pc.identified_gaps:
        lines += ["## Identified Gaps (your main focus)"]
        for gap in pc.identified_gaps:
            lines.append(f"- [{gap.severity.upper()}] {gap.area}: {gap.description}")
        lines.append("")

    lines += ["## Available Context Items", ""]
    for item in payload.context_items:
        text = context_texts.get(item.key, item.excerpt)
        lines += [f"@context:{item.key}", f"[{item.display_name}]", text, ""]

    lines += ["## Discovery Questions (ask in priority order, skip if already answered)"]
    for i, q in enumerate(
        sorted(payload.discovery_questions, key=lambda x: (x.priority, x.id)), start=1
    ):
        refs = (
            f" (see {', '.join('@context:' + r for r in q.context_item_refs)})"
            if q.context_item_refs
            else ""
        )
        lines.append(f"{i}. [{q.category.upper()}]{refs} {q.question_text}")

    lines += [
        "",
        "## Session Start",
        "Introduce yourself in 1-2 sentences, confirm you reviewed the uploaded materials, "
        "then ask your first question.",
    ]

    return "\n".join(lines)
