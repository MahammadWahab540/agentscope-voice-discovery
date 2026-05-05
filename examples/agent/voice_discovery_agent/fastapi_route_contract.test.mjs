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
const deleteRoute = server.match(
  /@app\.delete\("\/sessions\/\{session_id\}", status_code=204\)([\s\S]*?)async def end_session\(([\s\S]*?)\) -> ([^:\n]+):/,
);

run("204 delete route does not declare a JSON response body", () => {
  assert.ok(deleteRoute, "delete route signature should be present");
  assert.doesNotMatch(
    deleteRoute[3],
    /JSONResponse/,
    "204 routes must not advertise a response body type",
  );
});
