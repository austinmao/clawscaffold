// @ts-nocheck
// ClawScaffold (Scaffold Planner) — OpenClaw gateway bridge plugin
// Registers scaffold_analyze, scaffold_next_question, scaffold_answer, scaffold_finalize
// Uses @ts-nocheck to avoid openclaw/plugin-sdk import resolution bug (#53002)
// Part of the ClawSuite: https://github.com/austinmao/clawscaffold

import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import { constants as fsConstants } from "node:fs";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

function resolveConfig(api) {
  const cfg = api?.pluginConfig ?? {};
  const repoRoot = (typeof cfg.repoRoot === "string" && cfg.repoRoot.trim()) ||
    process.env.OPENCLAW_WORKSPACE || process.cwd();
  const pythonBin = (typeof cfg.pythonBin === "string" && cfg.pythonBin.trim()) ||
    "python3";
  const timeoutMs = (typeof cfg.timeoutMs === "number" && Number.isFinite(cfg.timeoutMs))
    ? cfg.timeoutMs : 30_000;
  return { repoRoot, pythonBin, timeoutMs };
}

function textResult(payload) {
  return { content: [{ type: "text", text: JSON.stringify(payload) }] };
}

async function runPlannerCli(pythonBin, repoRoot, args, timeoutMs, extraEnv) {
  const commandArgs = ["scripts/scaffold.py", "interview-agent", ...args];
  const { stdout, stderr } = await execFileAsync(pythonBin, commandArgs, {
    cwd: repoRoot, timeout: timeoutMs, maxBuffer: 1024 * 1024,
    env: { ...process.env, ...extraEnv },
  });
  const raw = stdout.trim();
  if (!raw) throw new Error(`planner CLI empty stdout${stderr ? ` (${stderr.trim()})` : ""}`);
  try { return JSON.parse(raw); }
  catch (e) { throw new Error(`planner CLI non-JSON: ${raw.slice(0, 300)}`, { cause: e }); }
}

async function pathExists(targetPath) {
  try { await fs.access(targetPath, fsConstants.F_OK); return true; }
  catch { return false; }
}

async function withTempContentFile(content, fn) {
  if (typeof content !== "string") return fn();
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-scaffold-"));
  const contentFile = path.join(tempDir, "content.txt");
  try {
    await fs.writeFile(contentFile, content, "utf8");
    return await fn(contentFile);
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      try { resolve(JSON.parse(Buffer.concat(chunks).toString())); }
      catch { resolve({}); }
    });
    req.on("error", reject);
  });
}

export function register(api) {
  const { repoRoot, pythonBin, timeoutMs } = resolveConfig(api);

  api.registerTool({
    name: "scaffold_analyze",
    description: "Analyze a scaffold target and start or resume a deterministic interview run.",
    parameters: {
      type: "object", additionalProperties: false,
      properties: {
        mode: { type: "string", enum: ["create", "adopt", "extend"] },
        target_kind: { type: "string", enum: ["agent", "skill"] },
        target_id: { type: "string", minLength: 1 },
        execution_style: { type: "string", enum: ["interactive", "accept_recommendations"] },
        resume_run_id: { type: "string", minLength: 1 },
      },
      required: ["mode", "target_kind", "target_id"],
    },
    async execute(_id, params) {
      const args = ["analyze", "--mode", String(params.mode), "--kind", String(params.target_kind), "--id", String(params.target_id)];
      if (params.execution_style) args.push("--execution-style", String(params.execution_style));
      if (params.resume_run_id) args.push("--resume", String(params.resume_run_id));
      return textResult(await runPlannerCli(pythonBin, repoRoot, args, timeoutMs));
    },
  }, { optional: true });

  api.registerTool({
    name: "scaffold_next_question",
    description: "Fetch the next planner question for an in-progress scaffold interview run.",
    parameters: {
      type: "object", additionalProperties: false,
      properties: { run_id: { type: "string", minLength: 1 } },
      required: ["run_id"],
    },
    async execute(_id, params) {
      return textResult(await runPlannerCli(pythonBin, repoRoot, ["next-question", "--run-id", String(params.run_id)], timeoutMs));
    },
  }, { optional: true });

  api.registerTool({
    name: "scaffold_answer",
    description: "Record one planner answer in an in-progress scaffold interview run.",
    parameters: {
      type: "object", additionalProperties: false,
      properties: {
        run_id: { type: "string", minLength: 1 },
        question_id: { type: "string", minLength: 1 },
        choice: { type: "string" },
        content: { type: "string" },
        value_json: {},
      },
      required: ["run_id", "question_id"],
    },
    async execute(_id, params) {
      const content = typeof params.content === "string" ? params.content : undefined;
      return textResult(await withTempContentFile(content, async (contentFile) => {
        const args = ["answer", "--run-id", String(params.run_id), "--question-id", String(params.question_id)];
        if (params.choice) args.push("--choice", String(params.choice));
        if (contentFile) args.push("--content-file", contentFile);
        if (params.value_json !== undefined) args.push("--value-json", JSON.stringify(params.value_json));
        return runPlannerCli(pythonBin, repoRoot, args, timeoutMs);
      }));
    },
  }, { optional: true });

  api.registerTool({
    name: "scaffold_finalize",
    description: "Finalize a scaffold interview run into a reviewable draft.",
    parameters: {
      type: "object", additionalProperties: false,
      properties: {
        run_id: { type: "string", minLength: 1 },
        accept_recommendations: { type: "boolean" },
      },
      required: ["run_id"],
    },
    async execute(_id, params) {
      const args = ["finalize", "--run-id", String(params.run_id)];
      if (params.accept_recommendations === true) args.push("--accept-recommendations");
      return textResult(await runPlannerCli(pythonBin, repoRoot, args, timeoutMs));
    },
  }, { optional: true });

  // --- HTTP webhook routes ---

  api.registerHttpRoute({
    path: "/clawscaffold/analyze",
    auth: "gateway",
    match: "exact",
    handler: async (req, res) => {
      const body = await readBody(req);
      const args = ["analyze"];
      if (body.mode) args.push("--mode", String(body.mode));
      if (body.kind) args.push("--kind", String(body.kind));
      if (body.id) args.push("--id", String(body.id));
      if (body.execution_style) args.push("--execution-style", String(body.execution_style));
      try {
        const result = await runPlannerCli(pythonBin, repoRoot, args, timeoutMs);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result));
      } catch (err) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ status: "error", error: err.message }));
      }
    },
  });

  api.registerHttpRoute({
    path: "/clawscaffold/next-question",
    auth: "gateway",
    match: "exact",
    handler: async (req, res) => {
      const body = await readBody(req);
      const args = ["next-question"];
      if (body.run_id) args.push("--run-id", String(body.run_id));
      try {
        const result = await runPlannerCli(pythonBin, repoRoot, args, timeoutMs);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result));
      } catch (err) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ status: "error", error: err.message }));
      }
    },
  });

  api.registerHttpRoute({
    path: "/clawscaffold/answer",
    auth: "gateway",
    match: "exact",
    handler: async (req, res) => {
      const body = await readBody(req);
      const args = ["answer"];
      if (body.run_id) args.push("--run-id", String(body.run_id));
      if (body.answer) args.push("--answer", String(body.answer));
      try {
        const result = await runPlannerCli(pythonBin, repoRoot, args, timeoutMs);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result));
      } catch (err) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ status: "error", error: err.message }));
      }
    },
  });

  api.registerHttpRoute({
    path: "/clawscaffold/finalize",
    auth: "gateway",
    match: "exact",
    handler: async (req, res) => {
      const body = await readBody(req);
      const args = ["finalize"];
      if (body.run_id) args.push("--run-id", String(body.run_id));
      if (body.accept_recommendations === true) args.push("--accept-recommendations");
      try {
        const result = await runPlannerCli(pythonBin, repoRoot, args, timeoutMs);
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(result));
      } catch (err) {
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ status: "error", error: err.message }));
      }
    },
  });

  console.log("[clawscaffold] 4 tools + 4 HTTP routes registered");
}

export function activate(api) { register(api); }
export default { register, activate };
