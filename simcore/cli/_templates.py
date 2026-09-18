"""Pinning the prompt templates a run rendered: the templates are code, so the pin hashes it.

Every turn records the template it rendered and the hash of its exact prompt; the run
configuration pins the template behind those prompts. A prompt change moves the hash,
and a resume under moved templates refuses rather than continuing one study under two
wordings.
"""

from __future__ import annotations

import hashlib
import inspect

import simcore.agent._context as agent_context
import simcore.agent._prompt as agent_prompt


def template_hashes(template_ids: tuple[str, ...] = ("persona_turn", "persona_turn_strict", "persona_reflection", "persona_probe")) -> dict[str, str]:
    """One content hash per template id, over the source that renders it."""
    material = inspect.getsource(agent_prompt) + inspect.getsource(agent_context)
    return {
        template_id: hashlib.sha256(f"{template_id}\n{material}".encode("utf-8")).hexdigest()
        for template_id in template_ids
    }
