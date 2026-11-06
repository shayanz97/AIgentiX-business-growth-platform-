"""robots.txt policy (RFC 9309): 4xx = no restrictions, 5xx = assume everything is disallowed.

Fetch errors (DNS failure, blocked destination, timeouts) propagate so the caller reports the real cause
(and retries transient ones) instead of a misleading robots denial.
"""

from dataclasses import dataclass
from urllib.robotparser import RobotFileParser

from aigentix.modules.lead_intelligence.integrations.fetcher import SafeFetcher


@dataclass
class RobotsPolicy:
    parser: RobotFileParser | None  # None = no restrictions
    disallow_all: bool = False
    crawl_delay: float | None = None

    def allows(self, user_agent_token: str, url: str) -> bool:
        if self.disallow_all:
            return False
        return True if self.parser is None else self.parser.can_fetch(user_agent_token, url)


def load_robots(fetcher: SafeFetcher, origin: str, user_agent_token: str) -> RobotsPolicy:
    page = fetcher.get(origin.rstrip("/") + "/robots.txt")
    if 400 <= page.status < 500:
        return RobotsPolicy(parser=None)
    if not page.ok:
        return RobotsPolicy(parser=None, disallow_all=True)
    parser = RobotFileParser()
    parser.parse(page.body[:500_000].decode("utf-8", errors="replace").splitlines())
    delay = parser.crawl_delay(user_agent_token)
    return RobotsPolicy(parser=parser, crawl_delay=float(delay) if delay is not None else None)
