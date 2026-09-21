import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import improve from "../improve.ts";

for (const name of ["IMPROVE_DATA_DIR", "IMPROVE_MEMORY_DIR", "IMPROVE_PROJECT_DIR"]) delete process.env[name];

// Real Python hooks and MCP service; only the pi event/UI surface is a fixture.
function host(cwd: string) {
  const handlers = new Map();
  const tools = new Map();
  const notices: string[] = [];
  improve({
    on: (name, handler) => handlers.set(name, handler),
    registerTool: (tool) => tools.set(tool.name, tool),
  } as any);
  const ctx = { cwd, ui: { notify: (text: string) => notices.push(text) } };
  return {
    tools, notices,
    emit: (name: string, event = {}) => handlers.get(name)(event, ctx),
    async call(name: string, args: object, directory = cwd, signal?: AbortSignal) {
      const result = await tools.get(name).execute("test", args, signal, undefined, { cwd: directory });
      return JSON.parse(result.content[0].text);
    },
  };
}

test("pi shares memory, isolates projects, and refreshes startup context", async () => {
  const project = await mkdtemp(join(tmpdir(), "improve pi 项目 "));
  const other = await mkdtemp(join(tmpdir(), "improve pi other "));
  const pi = host(project);
  try {
    await pi.emit("session_start");
    assert.deepEqual(pi.notices, []);
    assert.deepEqual([...pi.tools.keys()].sort(), ["memory", "memory_recall"]);
    const initial = { systemPrompt: "Base prompt", systemPromptOptions: { sections: { existing: "keep" } } };
    assert.equal(await pi.emit("before_agent_start", initial), undefined);
    assert.match(initial.systemPromptOptions.sections.improve_toolkit, /^Improve Toolkit/);
    assert.equal(initial.systemPromptOptions.sections.existing, "keep");
    const added = await pi.call("memory", {
      action: "add", target: "memory", content: "Project uses cedar fixtures.", summary: "Cedar fixtures", startup: "always",
    });
    assert.equal(added.success, true);
    const recalled = await pi.call("memory_recall", { query: "cedar" });
    assert.equal(recalled.entries.length, 1);
    assert.equal(recalled.entries[0].content, "Project uses cedar fixtures.");
    assert.match(await readFile(join(project, ".improve-toolkit/memories/MEMORY.md"), "utf8"), /cedar/);
    assert.match(await readFile(join(project, ".improve-toolkit/.gitignore"), "utf8"), /^\*$/m);
    assert.equal((await pi.call("memory_recall", { query: "cedar" }, other)).entries.length, 0);
    assert.equal((await pi.call("memory_recall", { query: "cedar", project_dir: project }, other)).entries.length, 1);
    assert.equal((await pi.call("memory_recall", { query: "cedar", project_dir: "relative" })).success, false);
    await pi.emit("session_compact");
    const refreshed = { systemPrompt: "Base prompt", systemPromptOptions: { sections: {} } };
    await pi.emit("before_agent_start", refreshed);
    assert.match(refreshed.systemPromptOptions.sections.improve_toolkit, /Cedar fixtures/);
    assert.equal(refreshed.systemPromptOptions.sections.improve_toolkit.split("Improve Toolkit provides").length, 2);
    await assert.rejects(pi.call("memory_recall", { query: "cedar" }, project, AbortSignal.abort()));
    await pi.emit("session_shutdown");
    await pi.emit("session_shutdown");
    await assert.rejects(pi.call("memory_recall", { query: "cedar" }), /unavailable/);
    await pi.emit("session_start", { reason: "resume" });
    assert.deepEqual(pi.notices, []);
    const resumed = { systemPrompt: "Base", systemPromptOptions: { sections: {} } };
    await pi.emit("before_agent_start", resumed);
    assert.match(resumed.systemPromptOptions.sections.improve_toolkit, /Cedar fixtures/);
    assert.equal((await pi.call("memory_recall", { query: "cedar" })).entries.length, 1);
  } finally {
    await pi.emit("session_shutdown");
    await rm(project, { recursive: true, force: true });
    await rm(other, { recursive: true, force: true });
  }
});

test("bad Python override reports failure without breaking pi startup", async () => {
  const project = await mkdtemp(join(tmpdir(), "improve-pi-failure-"));
  const previous = process.env.IMPROVE_PYTHON;
  process.env.IMPROVE_PYTHON = join(project, "missing-python");
  const pi = host(project);
  try {
    await pi.emit("session_start");
    assert.equal(pi.tools.size, 0);
    assert.match(pi.notices[0], /Python 3.10/);
    const prompt = { systemPrompt: "Base", systemPromptOptions: { sections: {} } };
    await pi.emit("before_agent_start", prompt);
    assert.match(prompt.systemPromptOptions.sections.improve_toolkit, /unavailable/);
  } finally {
    await pi.emit("session_shutdown");
    if (previous === undefined) delete process.env.IMPROVE_PYTHON;
    else process.env.IMPROVE_PYTHON = previous;
    await rm(project, { recursive: true, force: true });
  }
});
