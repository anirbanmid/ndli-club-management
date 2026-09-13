"""
NDLI Club Management - State and Zone Mapping Module
Handles exact regional grouping of Indian States and Union Territories.
"""
from typing import Dict, List, Optional

# Strict Zone-to-States Mapping as per NDLI Club Specification
ZONE_STATE_MAP: Dict[str, List[str]] = {
    "North": [
        "Jammu & Kashmir",
        "Ladakh",
        "Uttarakhand",
        "Himachal Pradesh",
        "Chandigarh",
        "Punjab",
        "Haryana",
        "Delhi",
        "Uttar Pradesh"
    ],
    "Central": [
        "Madhya Pradesh",
        "Chhattisgarh"
    ],
    "West": [
        "Rajasthan",
        "Gujarat",
        "Maharashtra",
        "Goa",
        "Daman and Diu",
        "Dadar & Nagar Haveli"
    ],
    "East": [
        "Bihar",
        "Jharkhand",
        "West Bengal",
        "Odisha"
    ],
    "North East": [
        "Sikkim",
        "Assam",
        "Arunachal Pradesh",
        "Meghalaya",
        "Manipur",
        "Tripura",
        "Nagaland",
        "Mizoram"
    ],
    "South": [
        "Andhra Pradesh",
        "Telangana",
        "Karnataka",
        "Tamil Nadu",
        "Puducherry",
        "Kerala",
        "Andaman & Nicobar Island",
        "Lakshadweep"
    ]
}

# Inverted index for O(1) state-to-zone lookup with normalized keys
STATE_TO_ZONE: Dict[str, str] = {}
NORMALIZED_STATE_NAMES: Dict[str, str] = {}

def _normalize_name(name: str) -> str:
    """Normalize state name by removing extra punctuation, spaces, and lowering case."""
    if not name:
        return ""
    # Standardize ampersand and 'and'
    cleaned = name.strip().lower()
    cleaned = cleaned.replace("&", "and")
    cleaned = cleaned.replace("-", " ")
    cleaned = cleaned.replace(".", "")
    cleaned = " ".join(cleaned.split())
    return cleaned

# Build lookup dictionaries
for zone, states in ZONE_STATE_MAP.items():
    for state in states:
        norm_key = _normalize_name(state)
        STATE_TO_ZONE[norm_key] = zone
        NORMALIZED_STATE_NAMES[norm_key] = state

# Common spelling/formatting variations and aliases
ALIASES = {
    "jammu and kashmir": "Jammu & Kashmir",
    "j&k": "Jammu & Kashmir",
    "j and k": "Jammu & Kashmir",
    "dadra and nagar haveli": "Dadar & Nagar Haveli",
    "dadra & nagar haveli": "Dadar & Nagar Haveli",
    "dnh": "Dadar & Nagar Haveli",
    "daman & diu": "Daman and Diu",
    "andaman and nicobar islands": "Andaman & Nicobar Island",
    "andaman and nicobar island": "Andaman & Nicobar Island",
    "andaman & nicobar islands": "Andaman & Nicobar Island",
    "pondicherry": "Puducherry",
    "orissa": "Odisha",
    "nct of delhi": "Delhi",
    "delhi ncr": "Delhi",
}

for alias, target_state in ALIASES.items():
    norm_alias = _normalize_name(alias)
    norm_target = _normalize_name(target_state)
    if norm_target in STATE_TO_ZONE:
        STATE_TO_ZONE[norm_alias] = STATE_TO_ZONE[norm_target]
        NORMALIZED_STATE_NAMES[norm_alias] = NORMALIZED_STATE_NAMES[norm_target]


def get_zone_for_state(state_name: str) -> Optional[str]:
    """
    Returns the mapped Zone ('North', 'Central', 'West', 'East', 'North East', 'South')
    for a given Indian State or Union Territory name.
    Returns None if state is unrecognized.
    """
    if not state_name or not isinstance(state_name, str):
        return None
    normalized = _normalize_name(state_name)
    return STATE_TO_ZONE.get(normalized)


def get_canonical_state_name(state_name: str) -> Optional[str]:
    """Returns official canonical state name or None if not found."""
    if not state_name:
        return None
    normalized = _normalize_name(state_name)
    return NORMALIZED_STATE_NAMES.get(normalized)


def get_all_states() -> List[str]:
    """Returns sorted list of all supported canonical Indian States and UTs."""
    states = []
    for s_list in ZONE_STATE_MAP.values():
        states.extend(s_list)
    return sorted(states)


def get_all_zones() -> List[str]:
    """Returns list of all predefined zones."""
    return list(ZONE_STATE_MAP.keys())


def get_states_by_zone(zone_name: str) -> List[str]:
    """Returns list of states falling under a specific zone."""
    for z, states in ZONE_STATE_MAP.items():
        if z.lower() == zone_name.strip().lower():
            return states.copy()
    return []
