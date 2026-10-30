# AI Sales Agent — 100% Accuracy Challenge 🚀

A production-grade, conversational sales agent powered by a **Deterministic Orchestrator & Guardrail Engine** architecture. Guarantees 100% accuracy across catalog fetching, exact capacity calculations, strict discount escalation rules, mid-conversation change confirmation, and idempotent booking concurrency.

---

## 🎯 Architecture: How 100% Accuracy is Guaranteed

In real-world conversations, standard LLMs hallucinate calculations, leak unauthorized discounts, jump straight to maximum discounts, book stale numbers after mid-turn changes, or suffer race conditions on double-booking.

This project solves all these issues using a **hybrid NLU + Deterministic Policy Engine**:

```
User Turn ──> Intent & Entity Extractor ──> Session Lock ──> Deterministic Policy Engine
                                                                       │
┌──────────────────────────────────────────────────────────────────────┴──────────────────────────────────────┐
│  • Catalog Matching & Out-of-Catalog Shield (Rejects Netgear Orbi, matches 'arrow mesh wifi')              │
│  • Exact Quantity Math: ceil(required_capacity / max_capacity_per_unit)                                     │
│  • Strict Discount Ladder: 0% -> SAVE10 (10%) -> CLOSENOW15 (15% max), disallows SAVE50                    │
│  • Mid-Turn Change Gate: Invalidate confirmation if requirement changes, re-quote, require confirmation     │
│  • Concurrency & Idempotency Lock: Handles rapid double-clicks while create_booking (~1.2s) runs           │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                                       │
                                              Outgoing Verified API Calls & Audit Logs
                                              • GET /api/catalog
                                              • POST /api/bookings
```

---

## 📋 Scenario Matrix & Coverage

| Scenario | Challenge Requirement | Architectural Enforcement | Automated Test |
| :--- | :--- | :--- | :--- |
| **Scenario 1** | Typo matching ("arrow mesh wifi"), exact unit calculation (`5 rooms / 2 = 3 units`, $1,497) | Regex fuzzy synonym matcher + `math.ceil()` calculation | `test_scenario_1_exact_quantity_calculation` |
| **Scenario 1b** | Non-catalog rejection ("Netgear Orbi router") | Out-of-catalog classifier; polite refusal listing catalog; never books | `test_scenario_1b_non_catalog_rejection` |
| **Scenario 2** | Strict discount ladder: Quote standard first (0%), 1st pushback = `SAVE10` (10%), 2nd = `CLOSENOW15` (15% max). Disallow skipping or custom codes (e.g. `SAVE50`) | Stateful objection counter (0 -> 1 -> 2); rigid promo code mapping; math enforcement | `test_scenario_2_strict_discount_rules` |
| **Scenario 3** | Mid-conversation changes ("Change to 7 rooms and book it") | Signature tracking: if requirements change, booking is blocked, updated quote is presented, user must re-confirm | `test_scenario_3_discuss_before_booking_and_mid_conversation_changes` |
| **Scenario 4** | Interruptions & repeated booking confirmations ("Yes, book it!" twice while running ~1.2s) | Session-level `threading.Lock` + `threading.Condition` + Idempotency keys; exactly 1 booking API call | `test_scenario_4_interruptions_and_double_booking_concurrency` |

---

## 🏃 Quick Start Guide

### 1. Run Automated Test Suite (100% Pass)
```bash
cd /Users/sakthi/Documents/projects/ai_sales_agent
python3 -m unittest discover tests -v
```

### 2. Interactive Terminal CLI
Chat directly with the bot in terminal with live state inspector and API logs:
```bash
cd /Users/sakthi/Documents/projects/ai_sales_agent
python3 cli.py
```

### 3. Interactive Web Dashboard & REST API
Start the Flask web app:
```bash
cd /Users/sakthi/Documents/projects/ai_sales_agent
python3 app.py
```
Open **http://127.0.0.1:5001** in your browser.
- **Left Panel**: Chat conversation with pre-built 1-click scenario test chips.
- **Right Panel (Top)**: Real-time session state inspector (SKU, Plan, Capacity, Quantity, Discount Tier, Total Price, Order Status).
- **Right Panel (Bottom)**: Real-time API audit stream showing every `GET /api/catalog` and `POST /api/bookings` call with payload JSON, HTTP status, and latency.
- **Top Header**: "⚡ Test Double-Click Concurrency" button to test Scenario 4 live in the browser!

---

## 📡 REST API Reference

### 1. `GET /api/catalog`
Fetches available packages, capacities, plans, and pricing.
- **Query Parameter**: `query` (optional search keyword)
- **Sample Output**:
```json
{
  "SKU_AIRPODS_PRO2": {
    "name": "AirPods Pro 2nd Gen",
    "max_capacity_per_unit": 1,
    "plans": { "STD": 249.0, "CARE": 279.0 }
  },
  "SKU_MESH_WIFI6": {
    "name": "AeroMesh Wi-Fi 6E Home Pack",
    "max_capacity_per_unit": 2,
    "plans": { "STD": 399.0, "PRO": 499.0 }
  },
  "SKU_TEAM_HUB": {
    "name": "SyncHub Conference Bar",
    "max_capacity_per_unit": 3,
    "plans": { "STD": 899.0, "PRO": 1150.0 }
  }
}
```

### 2. `POST /api/bookings`
Creates final booking after user discussion. Simulates ~1.2s latency.
- **Payload**:
```json
{
  "sku_id": "SKU_MESH_WIFI6",
  "plan_code": "PRO",
  "quantity": 3,
  "promo_code": "CLOSENOW15",
  "final_price": 1272.45
}
```
- **Response (`201 Created`)**:
```json
{
  "booking_id": "BK-A1B2C3D4",
  "sku_id": "SKU_MESH_WIFI6",
  "product_name": "AeroMesh Wi-Fi 6E Home Pack",
  "plan_code": "PRO",
  "quantity": 3,
  "promo_code": "CLOSENOW15",
  "final_price": 1272.45,
  "status": "CONFIRMED"
}
```

### 3. `POST /api/chat`
Processes conversational turns with state tracking.
- **Payload**: `{"session_id": "string", "message": "string"}`
- **Response**: `{"reply": "string", "session_state": {...}, "catalog_logs": [...], "booking_logs": [...]}`

### 4. `GET /api/logs`
Returns the full audit trail of outgoing GET catalog and POST booking requests.
