import sqlite3
import os
import sys
from dotenv import load_dotenv

# Load env to get DB_PATH
load_dotenv()
DB_PATH = os.getenv("SQLITE_DB_PATH", "./voice_discovery.db")

def check_session(target_id=None):
    print(f"Checking database: {os.path.abspath(DB_PATH)}")
    if not os.path.exists(DB_PATH):
        print("Database file not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 1. Get total count
    cur.execute("SELECT COUNT(*) FROM discovery_sessions")
    total = cur.fetchone()[0]
    print(f"Total sessions in DB: {total}")

    # 2. Check for target
    if target_id:
        cur.execute("SELECT session_id, user_id, status, voice_session_id FROM discovery_sessions WHERE session_id=?", (target_id,))
        row = cur.fetchone()
        if row:
            print(f"\n[MATCH FOUND] ID: {row[0]} | User: {row[1]} | Status: {row[2]} | VoiceSessionID: {row[3]}")
        else:
            print(f"\n[NOT FOUND] Session {target_id} is missing from THIS database.")
    
    # 3. List last 5 sessions
    cur.execute("SELECT session_id, user_id, status, created_at FROM discovery_sessions ORDER BY created_at DESC LIMIT 5")
    rows = cur.fetchall()
    print("\nMost recent 5 sessions:")
    for r in rows:
        print(f"  - {r[0]} | User: {r[1]} | Status: {r[2]} | Created: {r[3]}")

    conn.close()

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    check_session(target)
