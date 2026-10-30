"""
Catalog definitions, API retrieval, fuzzy matching, and out-of-catalog detection.
"""

import time
import re
from typing import Dict, Any, Optional, Tuple, List

# Official Catalog Data as specified in the challenge requirements
CATALOG_DATA: Dict[str, Dict[str, Any]] = {
    "SKU_AIRPODS_PRO2": {
        "name": "AirPods Pro 2nd Gen",
        "category": "Earbuds / Audio",
        "unit_description": "person",
        "max_capacity_per_unit": 1,
        "plans": {
            "STD": 249.0,
            "CARE": 279.0
        }
    },
    "SKU_MESH_WIFI6": {
        "name": "AeroMesh Wi-Fi 6E Home Pack",
        "category": "Mesh Wi-Fi / Networking",
        "unit_description": "room",
        "max_capacity_per_unit": 2,
        "plans": {
            "STD": 399.0,
            "PRO": 499.0
        }
    },
    "SKU_TEAM_HUB": {
        "name": "SyncHub Conference Bar",
        "category": "Video Conferencing / Meeting Hub",
        "unit_description": "person",
        "max_capacity_per_unit": 3,
        "plans": {
            "STD": 899.0,
            "PRO": 1150.0
        }
    }
}

# Synonyms and typo patterns for robust fuzzy matching
SKU_PATTERNS = {
    "SKU_MESH_WIFI6": [
        r"aeromesh", r"aero\s*mesh", r"arrow\s*mesh", r"mesh\s*wifi",
        r"wifi\s*6e?", r"home\s*pack", r"router\s*pack", r"mesh\s*network"
    ],
    "SKU_TEAM_HUB": [
        r"synchub", r"sync\s*hub", r"sink\s*hub", r"team\s*hub",
        r"conference\s*bar", r"meeting\s*bar", r"conference\s*hub"
    ],
    "SKU_AIRPODS_PRO2": [
        r"airpods?", r"air\s*pods?", r"earbuds?", r"apple\s*airpods?"
    ]
}

# Known non-catalog products for explicit rejection
KNOWN_NON_CATALOG = [
    r"netgear", r"orbi", r"google\s*nest", r"eero", r"asus\s*zenwifi",
    r"linksys", r"tp-?link", r"sony", r"bose", r"jabra", r"cisco",
    r"polycom", r"logitech", r"sennheiser"
]

# Audit log for catalog API calls
_catalog_api_log: List[Dict[str, Any]] = []


def get_catalog_api_logs() -> List[Dict[str, Any]]:
    """Return audit log of all catalog GET requests."""
    return list(_catalog_api_log)


def clear_catalog_logs() -> None:
    """Clear catalog logs for testing."""
    _catalog_api_log.clear()


def get_catalog_info(query: str = "") -> Dict[str, Any]:
    """
    GET API — Fetch available packages, capacities, and pricing.
    Can be filtered by query or returns full catalog.
    Logs the API call for auditing.
    """
    start_time = time.time()
    
    # Simulate slight network latency (20-30ms)
    time.sleep(0.02)
    
    clean_query = query.strip().lower()
    if clean_query:
        # Filter if matches
        matched = {}
        for sku, info in CATALOG_DATA.items():
            if (clean_query in sku.lower() or 
                clean_query in info["name"].lower() or 
                clean_query in info["category"].lower()):
                matched[sku] = info
        result = matched if matched else CATALOG_DATA
    else:
        result = CATALOG_DATA

    duration_ms = round((time.time() - start_time) * 1000, 2)
    log_entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "method": "GET",
        "endpoint": f"/api/catalog?query={query}",
        "query": query,
        "status_code": 200,
        "latency_ms": duration_ms,
        "response_keys": list(result.keys())
    }
    _catalog_api_log.append(log_entry)
    return result


def match_sku_from_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Matches SKU from user text using fuzzy regex patterns.
    Returns:
        (sku_id, None) if a catalog item is matched
        (None, non_catalog_detected_item) if a non-catalog item is detected
        (None, None) if no specific item was detected
    """
    lower = text.lower()
    
    # Check for known out-of-catalog items first
    for pattern in KNOWN_NON_CATALOG:
        match = re.search(pattern, lower)
        if match:
            return None, match.group(0)

    # Check for catalog SKU matches
    for sku, patterns in SKU_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, lower):
                return sku, None

    return None, None
