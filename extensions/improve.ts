/** pi adapter: keep memory schemas, storage, and startup prose in Python. */
import { execFile } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { TSchema } from "typebox";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const { version } = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
const exec = promisify(execFile);
const unavailable = "Improve Toolkit memory is unavailable. Do not assume there are no saved memories. Fix the reported startup error and run /reload.";

function environment(cwd: string): Record<string, string> {
  return {
    ...Object.fromEntries(Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined)),
    IMPROVE_HOST: "pi",
    IMPROVE_PROJECT_DIR: cwd,
    PYTHONIOENCODING: "utf-8",
  };
}

async function findPython(env: Record<string, string>) {
  const candidates = env.IMPROVE_PYTHON
    ? [[env.IMPROVE_PYTHON]]
    : [["py", "-3"], ["python3"], ["python"]];
  for (const [command, ...args] of candidates) {
    try {
      await exec(command, [...args, "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"], { env, timeout: 10000 });
      return { command, args };
    } catch {
      // Try the next interpreter; an explicit override has no fallback.
    }
  }
  throw new Error("Python 3.10+ not found. Check IMPROVE_PYTHON or install Python.");
}

export default function improve(pi: ExtensionAPI) {
  let client: Client | undefined;
  let transport: StdioClientTransport | undefined;
  let python: Awaited<ReturnType<typeof findPython>> | undefined;
  let context = unavailable;

  async function close() {
    const activeClient = client;
    const activeTransport = transport;
    client = undefined;
    transport = undefined;
    try {
      await activeClient?.close();
    } finally {
      await activeTransport?.close();
    }
  }

  async function refreshContext(ctx: ExtensionContext) {
    if (!python) throw new Error("Python is unavailable.");
    const sections = [];
    for (const script of ["session_context.py", "load_memory.py"]) {
      const { stdout } = await exec(python.command, [...python.args, join(root, "scripts", script)], {
        cwd: ctx.cwd, env: environment(ctx.cwd), timeout: 30000, maxBuffer: 1024 * 1024,
      });
      const text = JSON.parse(stdout).hookSpecificOutput?.additionalContext;
      if (typeof text !== "string") throw new Error(`Invalid startup output from ${script}`);
      if (text) sections.push(text);
    }
    context = sections.join("\n\n");
  }

  pi.on("session_start", async (_event, ctx) => {
    context = unavailable;
    await close();
    try {
      const env = environment(ctx.cwd);
      python = await findPython(env);
      await refreshContext(ctx);
      transport = new StdioClientTransport({
        command: python.command, args: [...python.args, join(root, "servers", "server.py")],
        cwd: ctx.cwd, env, stderr: "pipe",
      });
      // Drain stderr (including first-run pip output) without mixing it into MCP.
      let stderr = "";
      transport.stderr?.on("data", (chunk) => { stderr = (stderr + chunk.toString()).slice(-4000); });
      client = new Client({ name: "improve-toolkit-pi", version });
      try {
        await client.connect(transport, { timeout: 120000 });
      } catch (error) {
        throw new Error(`${error instanceof Error ? error.message : error}${stderr ? `\n${stderr}` : ""}`);
      }
      const { tools } = await client.listTools();
      for (const tool of tools) {
        if (tool.name !== "memory" && tool.name !== "memory_recall") continue;
        pi.registerTool({
          name: tool.name,
          label: tool.name === "memory" ? "Save memory" : "Recall memory",
          description: tool.description ?? tool.name,
          parameters: tool.inputSchema as TSchema,
          async execute(_id, params, signal, _onUpdate, toolContext) {
            if (!client) throw new Error(unavailable);
            const result = await client.callTool({
              name: tool.name,
              arguments: { ...params, project_dir: params.project_dir ?? toolContext.cwd },
            }, undefined, { signal, timeout: 120000 });
            // This server exposes text-only results; preserve its JSON verbatim.
            const content = result.content as Array<{ type: "text"; text: string }>;
            if (result.isError) throw new Error(content.map((item) => item.text).join("\n"));
            return { content, details: {} };
          },
        });
      }
    } catch (error) {
      await close();
      context = unavailable;
      ctx.ui.notify(`Improve Toolkit: ${error instanceof Error ? error.message : error}`, "error");
    }
  });

  pi.on("before_agent_start", async (event) => {
    event.systemPromptOptions.sections.improve_toolkit = context;
  });

  pi.on("session_compact", async (_event, ctx) => {
    if (!client) return;
    try {
      await refreshContext(ctx);
    } catch (error) {
      context = unavailable;
      ctx.ui.notify(`Improve Toolkit: ${String(error)}`, "error");
    }
  });

  pi.on("session_shutdown", close);
}
