"""
Deterministic synthetic scenarios.

Everything this package produces is fabricated. It exists so the analysis
pipeline can be exercised end to end without waiting for a real incident, and
so a reviewer can see what a finished investigation looks like.

Every record carries SYNTHETIC in its source and a `synthetic: True` marker, and
every scenario result carries a banner saying so. Nothing here may be presented
as evidence about a real machine, and the report generator prints the banner
wherever synthetic evidence appears.
"""

from .library import (  # noqa: F401
    SCENARIOS, SYNTHETIC_BANNER, build_scenario, list_scenarios, run_scenario,
)
