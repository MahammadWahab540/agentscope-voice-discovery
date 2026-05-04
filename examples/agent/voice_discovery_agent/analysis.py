import os
import asyncio
from session_store import store

async def analyze_project_explanation(session_id: str) -> str:
    """Analyze the transcript of a project explanation and provide feedback."""
    row = store.get_session(session_id)
    if not row:
        return "Session not found."
    
    transcript_rows = store.get_transcript(session_id)
    # Extract only the user's explanation (usually the long turn)
    user_turns = [t["content_text"] for t in transcript_rows if t["speaker"] == "user"]
    full_explanation = "\n\n".join(user_turns)
    
    if not full_explanation:
        return "No user explanation found to analyze."

    # Use a standard Gemini model for analysis (non-realtime)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "GEMINI_API_KEY is missing for analysis."

    prompt = f"""
    You are an expert communication coach and technical architect. 
    Analyze the following project explanation provided by a user and provide constructive feedback.

    PROJECT CONTEXT:
    {row.payload_json}

    USER EXPLANATION:
    {full_explanation}

    Provide feedback on the following criteria:
    1. Clarity of explanation: Was it easy to follow?
    2. Structure and flow: Did it have a clear beginning, middle, and end?
    3. Completeness of project details: Did they cover strategy, decisions, challenges, and outcomes?
    4. Confidence and tone: (Based on the text, infer from phrasing and vocabulary).
    5. Communication quality: Professionalism and technical accuracy.
    6. Missing or weak points: What was left out or vague?
    7. Suggestions for improvement: Actionable tips.

    Format the response as a professional feedback report in Markdown.
    """

    # We use a simple completion call here. 
    # For now, I'll use a placeholder implementation or try to use a library if available.
    # Since I don't want to add new heavy dependencies, I'll use a simple HTTP call to Gemini.
    
    import requests
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        feedback = result['candidates'][0]['content']['parts'][0]['text']
        return feedback
    except Exception as e:
        return f"Error during analysis: {str(e)}"
