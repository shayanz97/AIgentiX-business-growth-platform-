"""Follow-up logic (deterministic, no I/O): task buckets in a time zone and per-stage task suggestions.

Buckets are computed in the caller's IANA time zone so that "today" matches the user's calendar day:
  * overdue  - open and due_at is before now;
  * today    - open, not yet overdue, due before the end of today's local day;
  * upcoming - open, due on one of the next 7 local calendar days (tomorrow .. today + 7);
  * later    - open, due beyond that.
The buckets never overlap. Suggestions are advice derived from recorded deal state; they never create tasks and
never imply that any contact happened.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aigentix.core.errors import InvalidInput

DEFAULT_TZ = "Europe/Berlin"
UPCOMING_DAYS = 7


def parse_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise InvalidInput("Unknown time zone (use an IANA name such as Europe/Berlin)") from None


@dataclass(frozen=True)
class Boundaries:
    now: datetime
    tomorrow_start: datetime  # first instant of the next local day (UTC)
    upcoming_end: datetime  # exclusive end of the upcoming window (UTC)


def boundaries(now: datetime, tz: ZoneInfo) -> Boundaries:
    local_today = now.astimezone(tz).date()

    def midnight(days: int) -> datetime:
        return datetime.combine(local_today + timedelta(days=days), time.min, tzinfo=tz).astimezone(UTC)

    return Boundaries(now=now, tomorrow_start=midnight(1), upcoming_end=midnight(1 + UPCOMING_DAYS))


def bucket(due_at: datetime, status: str, b: Boundaries) -> str:
    """overdue | today | upcoming | later for open tasks; the task status otherwise."""
    if status != "open":
        return status
    if due_at < b.now:
        return "overdue"
    if due_at < b.tomorrow_start:
        return "today"
    if due_at < b.upcoming_end:
        return "upcoming"
    return "later"


# --- suggestions -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DealState:
    stage: str
    has_brief: bool
    days_since_contact: int | None  # age of the last recorded contact activity; None = none recorded
    open_suggestion_keys: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Suggestion:
    key: str
    title: str
    reason: str
    due_in_days: int


def suggest(state: DealState) -> list[Suggestion]:
    out: list[Suggestion] = []
    stage = state.stage
    if stage in ("qualified", "researching"):
        out.append(
            Suggestion(
                "review_research_findings",
                "Review research findings",
                "Check the evidence and the AI Opportunity Audit behind this lead before planning anything.",
                1,
            )
        )
        if state.has_brief:
            out.append(
                Suggestion(
                    "review_sales_brief",
                    "Review the sales brief",
                    "A brief exists; verify its claims against the cited evidence and edit it where needed.",
                    2,
                )
            )
    if stage in ("researching", "contact_planned"):
        out.append(
            Suggestion(
                "prepare_discovery_questions",
                "Prepare discovery questions",
                "Write down what you still need to learn about the company's processes and needs.",
                2,
            )
        )
    if stage == "contact_planned":
        out.append(
            Suggestion(
                "schedule_permitted_followup",
                "Schedule a permitted follow-up",
                "Check the contact's recorded permission for a channel first; AIgentiX sends nothing itself.",
                3,
            )
        )
    if stage == "in_conversation":
        silent = state.days_since_contact is None or state.days_since_contact >= 3
        if silent:
            age = (
                "No contact activity is recorded yet."
                if state.days_since_contact is None
                else f"The last recorded contact was {state.days_since_contact} days ago."
            )
            out.append(
                Suggestion(
                    "check_customer_reply", "Check status of customer reply", f"{age} See if a reply arrived.", 1
                )
            )
        if state.days_since_contact is not None and state.days_since_contact >= 7:
            out.append(
                Suggestion(
                    "schedule_permitted_followup",
                    "Schedule a permitted follow-up",
                    f"{state.days_since_contact} days without recorded contact; check permission before any follow-up.",
                    2,
                )
            )
    if stage == "proposal_sent":
        out.append(
            Suggestion(
                "review_submitted_proposal",
                "Review submitted proposal",
                "Re-read what was sent so you are prepared for questions.",
                1,
            )
        )
        out.append(
            Suggestion(
                "update_sales_outcome",
                "Update sales outcome",
                "When the customer decides, close the deal as won or lost with the recorded value or reason.",
                7,
            )
        )
    return [s for s in out if s.key not in state.open_suggestion_keys]
