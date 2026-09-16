"""Engine-free recomputation of the anchor check on Nova: raw vectors from the proxy, SSR in numpy, per-set diagnostics.

Usage: uv run python docs/evaluations/2026-09-17-elicitation-nova/independent_recompute.py <vector-cache-dir outside the repo>"""
import json, time, sys, itertools
from pathlib import Path
import httpx, numpy as np
from scipy.stats import spearmanr
from simcore.elicitation._check import LADDERS, VARIED_SETS

MODEL = "amazon.nova-2-multimodal-embeddings-v1:0"
S = Path(sys.argv[1]); cache = S / "nova_vectors.json"
vecs = json.loads(cache.read_text()) if cache.exists() else {}
def emb(text):
    if text not in vecs:
        for attempt in range(8):
            r = httpx.post("http://127.0.0.1:4000/v1/embeddings", json={"model": MODEL, "input": [text]}, timeout=60)
            if r.status_code == 200: break
            time.sleep(10)
        r.raise_for_status(); d = r.json(); assert d["model"] == MODEL, d["model"]
        vecs[text] = d["data"][0]["embedding"]; cache.write_text(json.dumps(vecs)); time.sleep(3.3)
    return np.asarray(vecs[text], dtype=np.float64)

def pmf(resp, anchors):
    a = np.stack([x / np.linalg.norm(x) for x in anchors]); r = resp / np.linalg.norm(resp)
    g = (1 + a @ r) / 2; p = g - g.min(); return p / p.sum()

for construct in ("purchase_intent", "satisfaction"):
    sets = json.loads(Path(f"anchors/{construct}/v1.json").read_text())["sets"]
    A = [[emb(t) for t in s] for s in sets]
    ladder = LADDERS[construct]
    L = [emb(t) for t in ladder]
    per_set = np.array([[pmf(l, A[k]) @ np.arange(1, 6) for l in L] for k in range(6)])  # sets x ladder
    head = [np.mean([pmf(l, A[k]) for k in range(6)], axis=0) @ np.arange(1, 6) for l in L]
    print(f"\n== {construct}  headline {np.round(head,3)}")
    for k in range(6): print(f"  set {k}: {np.round(per_set[k],2)}  rho vs ladder {spearmanr(per_set[k], range(7)).statistic:.3f}")
    pairs = {(i, j): spearmanr(per_set[i], per_set[j]).statistic for i, j in itertools.combinations(range(6), 2)}
    worst = min(pairs, key=pairs.get); print(f"  min pairwise rho {pairs[worst]:.3f} at sets {worst}")
    # anchor-to-anchor: does each set's own 5 anchors order themselves?
    for k in range(6):
        ranks = [int(np.argmax(pmf(A[k][i], A[k]))) + 1 for i in range(5)]
        print(f"  set {k} anchors self-argmax {ranks}")
