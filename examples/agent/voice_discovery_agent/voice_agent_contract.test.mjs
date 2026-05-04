import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

function run(name, fn) {
  try {
    fn();
    console.log(`ok - ${name}`);
  } catch (error) {
    console.error(`not ok - ${name}`);
    console.error(error);
    process.exitCode = 1;
  }
}

const server = readFileSync(new URL("./run_server.py", import.meta.url), "utf8");
const pool = readFileSync(new URL("./agent_pool.py", import.meta.url), "utf8");
const realtimeAgent = readFileSync(new URL("../../../src/agentscope/agent/_realtime_agent.py", import.meta.url), "utf8");

run("agent pool acquisition is timeout-bounded and supports cold fallback", () => {
  assert.match(pool, /asyncio\.wait_for\(/);
  assert.match(pool, /timeout/);
  assert.match(server, /create one-off|cold/i);
});

run("websocket route validates the URL user id against stored session owner", () => {
  assert.match(server, /row\.user_id\s*!=\s*user_id/);
  assert.match(server, /SESSION_USER_MISMATCH/);
});

run("realtime agent can reattach a session output queue without duplicate model connections", () => {
  assert.match(realtimeAgent, /async def attach_output_queue/);
  assert.match(server, /await agent\.attach_output_queue\(frontend_queue\)/);
  assert.match(server, /No pooled agent found[\s\S]+await agent\.start\(frontend_queue\)/);
});
