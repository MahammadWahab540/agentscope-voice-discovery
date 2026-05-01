from __future__ import annotations
import httpx
from models import ContextItem

MAX_CHARS_PER_ITEM = 3000


async def download_text_for_item(
    item: ContextItem, supabase_url: str, supabase_key: str
) -> str:
    if not item.storage_path:
        return item.excerpt[:MAX_CHARS_PER_ITEM]

    url = f"{supabase_url}/storage/v1/object/authenticated/{item.storage_path}"
    headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "text" in content_type or "json" in content_type:
                return resp.text[:MAX_CHARS_PER_ITEM]
            return item.excerpt[:MAX_CHARS_PER_ITEM]
    except Exception:
        return item.excerpt[:MAX_CHARS_PER_ITEM]


async def load_context_texts(
    items: list[ContextItem], supabase_url: str, supabase_key: str
) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        result[item.key] = await download_text_for_item(item, supabase_url, supabase_key)
    return result
