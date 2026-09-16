"""Run the holdout against a real endpoint through the production path, recording usage, cost and failures.

This is the script behind this evaluation's numbers. `python -m simcore.holdout` writes the same report; this
wraps the client to also meter every billed token and every failure kind, which the report does not carry.

    SIMCORE_INFERENCE_BASE_URL=https://bedrock-mantle.us-east-1.api.aws/v1 \
    SIMCORE_INFERENCE_API_KEY=<short-term Bedrock API key> \
      python docs/evaluations/2026-09-17-holdout-bedrock/run_holdout.py \
        --model deepseek.v3.2 --pool 20000 --information demographics --out report.json

Prices are the AWS Pricing API's us-east-1 standard on-demand rates on 2026-09-17, per million tokens."""
import argparse, json, sys, time
from collections import Counter
from pathlib import Path
import simcore.holdout.__main__ as cli
from simcore.brief import load_brief
from simcore.holdout import evaluate
from simcore.inference import ExecutionSettings, InferenceClient
from simcore.schemas import CallFailure, Completion, ModelPins

PRICES = {"mistral.ministral-3-8b-instruct": (0.15, 0.15), "openai.gpt-oss-120b": (0.15, 0.60), "deepseek.v3.2": (0.62, 1.85)}

class Metered:
    def __init__(self, client):
        self.client, self.tin, self.tout, self.calls, self.kinds, self.details = client, 0, 0, 0, Counter(), Counter()
    @property
    def served_models(self): return self.client.served_models
    def complete(self, requests):
        outcomes = self.client.complete(requests)
        for outcome in outcomes:
            self.calls += 1
            billed = (outcome.cost, *outcome.discarded_costs) if isinstance(outcome, Completion) else outcome.costs
            for cost in billed:
                if cost.route.value != "cache":
                    self.tin += cost.input_tokens; self.tout += cost.output_tokens
            if isinstance(outcome, Completion):
                self.kinds["completion"] += 1
            else:
                self.kinds[outcome.kind.value] += 1; self.details[outcome.detail[:110]] += 1
        return outcomes

p = argparse.ArgumentParser(); p.add_argument("--model"); p.add_argument("--pool", type=int); p.add_argument("--out"); p.add_argument("--information", default="demographics")
a = p.parse_args()
args = argparse.Namespace(pack=cli.DEFAULT_PACK, ontologies=Path("ontologies"), hidden="att_ai", pool=a.pool, cache=None, coreset_fixture=None, source="stackoverflow")
pack = load_brief(args.pack, args.ontologies)
coreset, rows = cli._rows(pack, ("att_ai",), args)
pins = ModelPins.model_validate({"tier_a": a.model, "tier_b": a.model, "embed": "unused/embed-v1"})
metered = Metered(InferenceClient(pins, ExecutionSettings.from_environment()))
started = time.time()
report = evaluate(pack, coreset, rows, hidden=("att_ai",), inference=metered, holdout_seed=4021, completion_temperature=1.0,
                  inference_label="bedrock-mantle", pins={"tier_a": a.model}, served_models=metered.served_models, information=a.information)
elapsed = time.time() - started
Path(a.out).write_text(report.to_json())
pin, pout = PRICES[a.model]
s = report.attributes["att_ai"]
print(json.dumps({
    "model": a.model, "information": a.information, "seconds": round(elapsed, 1), "calls": metered.calls, "outcomes": dict(metered.kinds),
    "failure_details": dict(metered.details.most_common(3)),
    "tokens_in": metered.tin, "tokens_out": metered.tout, "cost_usd": round((metered.tin * pin + metered.tout * pout) / 1e6, 5),
    "held_out": report.held_out_rows, "projected": s.projected_rows,
    "log_loss": s.log_loss, "baseline_log_loss": s.baseline_log_loss, "brier": s.brier, "baseline_brier": s.baseline_brier,
    "marginal_distance": s.marginal_distance, "baseline_marginal_distance": s.baseline_marginal_distance,
    "recovered_dependence": s.recovered_dependence, "baseline_recovered_dependence": s.baseline_recovered_dependence,
    "served": {k: sorted(v) for k, v in metered.served_models.items()},
}, indent=1))
