# Elicitation validates the text-to-rating mapping on human data, and records the simulation claim as owed

"SSR works" is two claims. The **mapping claim**: given what a person wrote, SSR recovers the rating that person
gave. The **simulation claim**: simulated personas' purchase-intent distributions for a product match real
people's. The architecture expected an acceptance gate against published human purchase-intent data; the paper's
57 surveys belong to a company and are not public, and no public benchmark of concept-test purchase intent with
free text is in hand.

Elicitation therefore validates the mapping claim, on public human product reviews — a person wrote the text and
gave the star rating, so the ground truth is real — scoring SSR's distributions against those stars with log loss,
Brier score and rank correlation, against a baseline that does not read the text. It is run small, on a few hundred
reviews balanced across stars, to move fast. The simulation claim is recorded as owed, and the engine's trust level
stays uncalibrated (ADR 0008) until a real purchase-intent benchmark exists.

Embeddings come from Amazon Titan Text Embeddings v2 on Bedrock, reached through a local LiteLLM proxy that also
serves the chat models, because neither of Bedrock's OpenAI-compatible endpoints serves embeddings and OpenAI's
embedding models are not offered on AWS. The paper used OpenAI `text-embedding-3-small`; whether SSR survives the
substitution is measured by the review validation, not assumed, with Cohere Embed v4 as the next candidate.

## Considered options

Relying on the paper's reported agreement was rejected: it was tuned on its own evaluation data and used different
anchors and a different embedding model. Running a purchase-intent survey with real people is the only direct test
of the simulation claim and remains the way to discharge it, but it is a project of its own, not a module gate.

## Consequences

Reviews measure satisfaction, not purchase intent, so the validation uses a satisfaction anchor set frozen before it
runs, and it validates the mechanism — not the purchase-intent anchors, whose construct the data does not contain.
Those rely on the no-human-data checks of ADR 0027. A passing review validation means SSR can read human text into
human ratings with this embedding model; it does not mean simulated purchase intent matches people's.
