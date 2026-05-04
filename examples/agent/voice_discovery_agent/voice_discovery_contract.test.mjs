import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("./test.html", import.meta.url), "utf8");
const server = readFileSync(new URL("./run_server.py", import.meta.url), "utf8");
const script = html.match(/<script>([\s\S]*)<\/script>/)?.[1] ?? "";

function run(name, fn) {
  try {
    fn();
    console.log(`ok - ${name}`);
  } catch (error) {
    console.error(`not ok - ${name}`);
    throw error;
  }
}

run("server loads local configuration and exposes the browser demo contract", () => {
  assert.match(server, /from dotenv import load_dotenv/);
  assert.match(server, /load_dotenv\(/);
  assert.match(server, /@app\.get\("\/test\.html"\)/);
  assert.match(server, /@app\.get\("\/api\/check-models"\)/);
});

run("server reads the internal service key from the request header", () => {
  assert.match(server, /Header/);
  assert.match(server, /alias="X-Internal-Secret"/);
});

run("demo page resolves the backend URL from its current origin instead of hardcoding a port", () => {
  assert.match(html, /function resolveApiBaseUrl/);
  assert.doesNotMatch(html, /fetch\('http:\/\/localhost:8001\/sessions'/);
});

run("demo page initializes model checks, websocket connection, microphone, and playback with debug logs", () => {
  assert.match(html, /async function initializePage/);
  assert.match(html, /checkAvailableModels/);
  assert.match(html, /connect/);
  assert.match(html, /ensurePlaybackAudioContext/);
  assert.match(html, /Microphone permission requested/);
  assert.match(html, /Audio playback started/);
});

run("demo page inline script parses", () => {
  assert.ok(script.length > 0, "script block should be present");
  new Function(script);
});
