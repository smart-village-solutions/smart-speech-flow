"""Log attributes the collector sets itself, after its allowlist has run.

The gateway never sends these, so they sit outside ALLOWED_ATTRIBUTE_KEYS, yet
they land in bronze and the silver view reads them. Every guard that compares
stored or projected keys against the allowlist has to admit exactly these.
"""

COLLECTOR_EVENT_NAME_KEY = "ssf.collector.event_name"
COLLECTOR_DERIVED_KEYS = frozenset({COLLECTOR_EVENT_NAME_KEY})
