/* What a refusal says, in words a person can read.

   The engine turns a request away with a reason — an attribute the corpus does not
   carry, a brief whose claim has no evidence — and that reason is the point of the
   refusal. Every layer between the engine and the screen passes it on rather than
   replacing it with a status code. This file has no framework in it so it can be
   tested by itself. */

type Problem = { loc?: unknown[]; msg?: unknown };

export function refusalText(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const { detail, error } = body as { detail?: unknown; error?: unknown };
    for (const said of [detail, error]) {
      if (typeof said === "string" && said.trim()) return said.trim();
      if (Array.isArray(said) && said.length) {
        const lines = (said as Problem[]).map((problem) => {
          const where = (problem.loc ?? []).filter((part) => part !== "body").join(".");
          const what = typeof problem.msg === "string" ? problem.msg : JSON.stringify(problem);
          return where ? `${where}: ${what}` : what;
        });
        return lines.join("\n");
      }
    }
  }
  return fallback;
}
