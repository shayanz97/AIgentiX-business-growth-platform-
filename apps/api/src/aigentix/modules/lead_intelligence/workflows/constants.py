RESEARCH_WORKFLOW = "lead_intelligence.company_research"

# (step name, progress % when the step starts)
STEPS: tuple[tuple[str, int], ...] = (
    ("validate_input", 2),
    ("fetch_website", 8),
    ("discover_relevant_pages", 20),
    ("extract_information", 55),
    ("save_evidence", 70),
    ("ai_opportunity_audit", 78),
    ("persist_results", 95),
)
STEP_NAMES = tuple(name for name, _ in STEPS)
