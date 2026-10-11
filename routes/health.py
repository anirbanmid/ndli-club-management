"""
routes/health.py - Health + state/zone mapping

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
from config import SUPPORT_TYPES
from state_zone_mapper import ZONE_STATE_MAP, get_all_states, get_all_zones, get_zone_for_state

# path == "/api/health"
def get_health(h, path, query_params):
    h._send_health_status()
    return

# path in ("/api/state-zone/map", "/api/states", "/api/states-zones")
def get_state_zone_map(h, path, query_params):
    all_st = get_all_states()
    h._send_json({
        "success": True,
        "zones": get_all_zones(),
        "zone_to_states": ZONE_STATE_MAP,
        "map": ZONE_STATE_MAP,
        "all_states": all_st,
        "states": all_st,
        "support_types": SUPPORT_TYPES,
        "total": len(all_st)
    })
    return

# path == "/api/state-zone/lookup"
def get_state_zone_lookup(h, path, query_params):
    state_param = query_params.get("state", [""])[0]
    zone = get_zone_for_state(state_param)
    h._send_json({
        "state": state_param,
        "zone": zone or "Unknown",
        "found": zone is not None
    })
    return
