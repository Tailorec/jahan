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

/* What a person calls a version: its name, else what tells it apart — its variant and price. */
export function versionName(sc: { label?: string | null; variant: { name: string }; price: { amount: number; currency: string } }): string {
  return sc.label?.trim() || `${sc.variant.name} · ${sc.price.amount} ${sc.price.currency}`;
}

/* What a person calls a world: its version's name, and which of the run's seeds it ran under (1-based). */
export function worldName(
  scenarios: readonly { scenario_hash?: string; label?: string | null; variant: { name: string }; price: { amount: number; currency: string } }[],
  seeds: readonly number[],
  world: { scenario_hash?: string; seed?: number } | undefined,
): string | null {
  if (!world) return null;
  const sc = scenarios.find((x) => x.scenario_hash && x.scenario_hash === world.scenario_hash) ?? (scenarios.length === 1 ? scenarios[0] : undefined);
  if (!sc) return null;
  const k = world.seed != null ? seeds.indexOf(world.seed) : -1;
  return seeds.length > 1 && k >= 0 ? `${versionName(sc)} · seed ${k + 1}` : versionName(sc);
}

