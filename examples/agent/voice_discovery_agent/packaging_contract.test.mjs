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

const requirements = readFileSync(new URL("./requirements.txt", import.meta.url), "utf8");
const pyproject = readFileSync(new URL("./pyproject.toml", import.meta.url), "utf8");

run("requirements install the local package definition used by Railway", () => {
  assert.match(pyproject, /name = "voice-discovery-agent"/);
  assert.match(
    requirements,
    /(^|\r?\n)\.(\r?\n|$)/,
    "requirements.txt must install the local package so pyproject dependencies are included",
  );
});
