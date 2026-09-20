import test from "node:test";
import assert from "node:assert/strict";
import { worldForCell } from "../lib/worlds.ts";

const two = { worldIds: ["aaa", "bbb"], scenarios: 1, seeds: 2 };

test("a finished world is the one its digest names for that seed", () => {
  const digests = [{ world_id: "aaa", seed: 4021 }, { world_id: "bbb", seed: 917731 }];
  assert.equal(worldForCell(digests, 4021, two), "aaa");
  assert.equal(worldForCell(digests, 917731, two), "bbb");
});

test("a seed whose world has not finished is not shown as the first world", () => {
  const digests = [{ world_id: "aaa", seed: 4021 }];
  assert.equal(worldForCell(digests, 917731, two), undefined);
  assert.equal(worldForCell([], 4021, two), undefined);
});

test("a study of one cell names its only world even before it has a digest", () => {
  assert.equal(worldForCell([], 4021, { worldIds: ["aaa"], scenarios: 1, seeds: 1 }), "aaa");
  assert.equal(worldForCell([], 4021, { worldIds: [], scenarios: 1, seeds: 1 }), undefined);
});
