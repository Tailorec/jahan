"""Error hierarchy; the CLI maps these to exit codes by class."""


class SimError(Exception):
    exit_code: int = 1


class GateFailure(SimError):
    exit_code = 2


class BudgetExhausted(SimError):
    exit_code = 3


class SchemaVersionError(SimError):
    exit_code = 5
