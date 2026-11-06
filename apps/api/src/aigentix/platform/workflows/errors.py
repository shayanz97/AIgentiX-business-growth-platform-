"""Exceptions a workflow handler raises to tell the runner what happened."""


class WorkflowError(Exception):
    """Permanent failure (e.g. invalid input, blocked website). Not retried.

    The message is shown to tenant users, so it must not contain internals or secrets.
    """


class TransientWorkflowError(WorkflowError):
    """Temporary failure (timeouts, rate limits, upstream 5xx). Retried with backoff until max_attempts.

    The message is shown to tenant users.
    """


class WorkflowCancelled(Exception):
    """Raised at a step boundary when cancellation was requested."""
