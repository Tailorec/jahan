import { NextResponse } from "next/server";
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { engineApiBase, engineFetch, engineRoot, readRunDetail } from "@/lib/server";

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const detail = await readRunDetail(id);
  if (!detail.summary) return NextResponse.json({ error: "run not found" }, { status: 404 });
  return NextResponse.json(detail);
}

async function readLaunch(id: string) {
  try {
    return JSON.parse(
      await fs.readFile(path.join(engineRoot(), "runs", id, "launch.json"), "utf8"),
    ) as { argv?: string[]; cwd?: string; pid?: number | null };
  } catch {
    return null;
  }
}

/* Cancel a run: stop the process, lose at most the tick in flight. Proxied
   to the engine API when it serves the record; otherwise the pid in
   launch.json is signalled and the interruption is marked, so the run reads
   partial and a resume picks up after the last closed tick. */
export async function DELETE(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (engineApiBase()) {
    try {
      return NextResponse.json(await engineFetch(`/api/runs/${id}`, { method: "DELETE" }));
    } catch (e) {
      return NextResponse.json({ error: String(e) }, { status: 502 });
    }
  }
  const launch = await readLaunch(id);
  let stopped = false;
  if (launch?.pid) {
    try {
      process.kill(launch.pid, "SIGTERM");
      stopped = true;
    } catch { /* already exited */ }
  }
  if (stopped) {
    await fs.writeFile(
      path.join(engineRoot(), "runs", id, "cancelled.json"),
      JSON.stringify({ stopped: true }, null, 2),
    );
  }
  return NextResponse.json({ run_id: id, stopped });
}

/* Resume a cancelled run: a re-run with the same id, skipping finished worlds. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const { action } = (await req.json().catch(() => ({}))) as { action?: string };
  if (action !== "resume") return NextResponse.json({ error: "unknown action" }, { status: 422 });
  if (engineApiBase()) {
    try {
      return NextResponse.json(
        await engineFetch(`/api/runs/${id}/resume`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: "{}",
        }),
        { status: 202 },
      );
    } catch (e) {
      return NextResponse.json({ error: String(e) }, { status: 502 });
    }
  }
  const launch = await readLaunch(id);
  if (!launch?.argv?.length) {
    return NextResponse.json({ error: `run ${id} was not started here and names no relaunch` }, { status: 409 });
  }
  if (launch.pid) {
    try {
      process.kill(launch.pid, 0);
      return NextResponse.json({ error: `run ${id} is already running` }, { status: 409 });
    } catch { /* not running — relaunch */ }
  }
  const child = spawn(launch.argv[0], launch.argv.slice(1), {
    cwd: launch.cwd ?? engineRoot(),
    detached: true,
    stdio: "ignore",
  });
  child.unref();
  await fs.writeFile(
    path.join(engineRoot(), "runs", id, "launch.json"),
    JSON.stringify({ ...launch, pid: child.pid ?? null }, null, 2),
  );
  await fs.rm(path.join(engineRoot(), "runs", id, "cancelled.json"), { force: true });
  return NextResponse.json({ run_id: id }, { status: 202 });
}
