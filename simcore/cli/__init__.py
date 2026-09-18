"""The way in: argument plumbing, error formatting and artefact writing.

Four commands, each printing the `run_id` that names what it produced. The CLI wires
modules together; it derives nothing, renders nothing and decides nothing a study did
not already state. Exit codes come from the exception class, mapped in one place.
"""

__all__: list[str] = []
