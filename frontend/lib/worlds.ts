/* Which world a scenario × seed cell is. The interface derives nothing (ADR 0045), and a world's id is a hash of
   its scenario, seed and population, so a cell's world is known only from what the engine has said: the digest
   a finished world writes names its seed. A cell with no digest is not the first world by default — a study
   still on its first seed would otherwise show that world's id, status and tick against every seed it has
   not reached. The one time the cell is known without a digest is when the study is a single cell. */

export interface WorldRef { world_id: string; seed: number }

export function worldForCell(
  digests: readonly WorldRef[],
  seed: number,
  study: { worldIds: readonly string[]; scenarios: number; seeds: number },
): string | undefined {
  const finished = digests.find((d) => d.seed === seed);
  if (finished) return finished.world_id;
  const singleCell = study.scenarios * study.seeds === 1 && study.worldIds.length === 1;
  return singleCell ? study.worldIds[0] : undefined;
}
