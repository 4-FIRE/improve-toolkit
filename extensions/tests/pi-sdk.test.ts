import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";

const root = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const npm = process.platform === "win32" ? "npm.cmd" : "npm";
let sdkPath = "";
try {
  // Optional real-host test using the user's globally installed npm package.
  const globalRoot = execFileSync(npm, ["root", "-g"], { encoding: "utf8" }).trim();
  sdkPath = join(globalRoot, "@earendil-works/pi-coding-agent/dist/index.js");
} catch { /* The adapter tests still run when pi is not installed globally. */ }

for (const name of ["IMPROVE_DATA_DIR", "IMPROVE_MEMORY_DIR", "IMPROVE_PROJECT_DIR"]) delete process.env[name];

test("installed pi loads the package, six skills, and callable memory tools", {
  skip: !existsSync(sdkPath) && "pi npm package not installed globally",
}, async () => {
  const { DefaultResourceLoader, SettingsManager, SessionManager, createAgentSession } = await import(pathToFileURL(sdkPath).href);
  const cwd = await mkdtemp(join(tmpdir(), "improve-pi-sdk-"));
  let session;
  try {
    const agentDir = join(cwd, "agent");
    const settingsManager = SettingsManager.inMemory({ packages: [root] });
    const resourceLoader = new DefaultResourceLoader({ cwd, agentDir, settingsManager });
    await resourceLoader.reload();
    assert.deepEqual(resourceLoader.getExtensions().errors, []);
    assert.equal(resourceLoader.getExtensions().extensions.length, 1);
    assert.deepEqual(resourceLoader.getSkills().diagnostics, []);
    assert.deepEqual(resourceLoader.getSkills().skills.map(s => s.name).sort(), [
      "domain-modeling", "grill-with-docs", "grilling", "improve", "roundtable", "simple",
    ]);
    ({ session } = await createAgentSession({
      cwd, agentDir, settingsManager, resourceLoader, sessionManager: SessionManager.inMemory(cwd),
    }));
    const errors = [];
    await session.bindExtensions({ onError: (error) => errors.push(error) });
    assert.deepEqual(errors, []);
    for (const name of ["memory", "memory_recall"]) {
      assert.ok(session.getActiveToolNames().includes(name), `${name} must be active`);
    }
    // Execute the pi-wrapped tool; no model request or user credentials needed.
    const tool = session.agent.state.tools.find(tool => tool.name === "memory_recall");
    const result = await tool.execute("smoke", { mode: "browse" }, undefined);
    assert.equal(JSON.parse(result.content[0].text).success, true);
  } finally {
    if (session) {
      await session.extensionRunner.emit({ type: "session_shutdown" });
      session.dispose();
    }
    await rm(cwd, { recursive: true, force: true });
  }
});
