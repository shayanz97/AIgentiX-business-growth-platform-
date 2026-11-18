"""Deal pipeline rules (deterministic). Stages describe recorded real-world events; nothing here is AI-driven.

* Ordinary moves follow TRANSITIONS; `won` / `lost` only through the explicit close action, and a closed deal only
  changes again through the explicit reopen action (with a reason).
* Evidence gates: `in_conversation` needs a recorded contact activity; `proposal_sent` needs a proposal that a
  person marked as sent. Generating a draft is not sending it; creating a task is not contact.
"""

from dataclasses import dataclass

from aigentix.modules.sales.models import ActivityType, Stage

OPEN_STAGES: tuple[Stage, ...] = (
    Stage.QUALIFIED,
    Stage.RESEARCHING,
    Stage.CONTACT_PLANNED,
    Stage.IN_CONVERSATION,
    Stage.PROPOSAL_SENT,
)
CLOSED_STAGES: tuple[Stage, ...] = (Stage.WON, Stage.LOST)
PIPELINE: tuple[Stage, ...] = (*OPEN_STAGES, *CLOSED_STAGES)

TRANSITIONS: dict[Stage, frozenset[Stage]] = {
    Stage.QUALIFIED: frozenset({Stage.RESEARCHING, Stage.CONTACT_PLANNED}),
    Stage.RESEARCHING: frozenset({Stage.QUALIFIED, Stage.CONTACT_PLANNED}),
    Stage.CONTACT_PLANNED: frozenset({Stage.RESEARCHING, Stage.IN_CONVERSATION}),
    Stage.IN_CONVERSATION: frozenset({Stage.CONTACT_PLANNED, Stage.PROPOSAL_SENT}),
    Stage.PROPOSAL_SENT: frozenset({Stage.IN_CONVERSATION}),
    Stage.WON: frozenset(),
    Stage.LOST: frozenset(),
}

CONTACT_ACTIVITIES = frozenset(
    {
        ActivityType.CALL,
        ActivityType.MEETING,
        ActivityType.EMAIL_RECEIVED,
        ActivityType.EMAIL_SENT,
        ActivityType.LETTER_SENT,
    }
)


@dataclass(frozen=True)
class StageFacts:
    """Recorded facts the gates look at."""

    has_contact_activity: bool
    has_sent_proposal: bool


class TransitionError(ValueError):
    """A stage change that the rules do not allow; the message is user-facing."""


def check_move(current: Stage, target: Stage, facts: StageFacts) -> None:
    if current in CLOSED_STAGES:
        raise TransitionError("The deal is closed. Reopen it first (with a reason).")
    if target in CLOSED_STAGES:
        raise TransitionError("Use the close action to record a won or lost outcome.")
    if target == current:
        raise TransitionError("The deal is already in this stage.")
    if target not in TRANSITIONS[current]:
        allowed = ", ".join(s.value for s in PIPELINE if s in TRANSITIONS[current])
        raise TransitionError(f"Cannot move from {current.value} to {target.value}. Allowed: {allowed}.")
    if target == Stage.IN_CONVERSATION and not facts.has_contact_activity:
        raise TransitionError("Record the call, meeting or e-mail exchange first: in_conversation needs a contact.")
    if target == Stage.PROPOSAL_SENT and not facts.has_sent_proposal:
        raise TransitionError("Mark a proposal as sent first: a generated draft has not been sent.")


def check_close(current: Stage, outcome: Stage) -> None:
    if outcome not in CLOSED_STAGES:
        raise TransitionError("A deal closes as won or lost.")
    if current in CLOSED_STAGES:
        raise TransitionError("The deal is already closed.")


def reopen_stage(history: list[str]) -> Stage:
    """The last open stage before the deal was closed (deals closed straight from `qualified` reopen there)."""
    for stage in reversed(history):
        if stage in {s.value for s in OPEN_STAGES}:
            return Stage(stage)
    return Stage.QUALIFIED
