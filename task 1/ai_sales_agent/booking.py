"""
Booking API service: create_booking, validation, latency simulation, and audit logging.
"""

import time
import uuid
import threading
from typing import Dict, Any, Optional, List
from catalog import CATALOG_DATA

# Simulated delay for create_booking (in seconds)
BOOKING_API_LATENCY = 1.2

# Global registry of created bookings
_bookings_registry: Dict[str, Dict[str, Any]] = {}
_booking_api_log: List[Dict[str, Any]] = []
_booking_lock = threading.Lock()


def get_booking_api_logs() -> List[Dict[str, Any]]:
    """Return all audit logs for create_booking calls."""
    with _booking_lock:
        return list(_booking_api_log)


def get_all_bookings() -> List[Dict[str, Any]]:
    """Return list of all registered bookings."""
    with _booking_lock:
        return list(_bookings_registry.values())


def clear_booking_registry() -> None:
    """Clear registered bookings and logs (useful for unit tests)."""
    with _booking_lock:
        _bookings_registry.clear()
        _booking_api_log.clear()


def calculate_expected_price(sku_id: str, plan_code: str, quantity: int, promo_code: Optional[str]) -> float:
    """Strictly computes the expected price according to catalog and discount rules."""
    if sku_id not in CATALOG_DATA:
        raise ValueError(f"Invalid SKU: {sku_id}")
    plans = CATALOG_DATA[sku_id]["plans"]
    if plan_code not in plans:
        raise ValueError(f"Invalid plan '{plan_code}' for SKU '{sku_id}'")
    if quantity < 1:
        raise ValueError(f"Quantity must be >= 1, got {quantity}")

    unit_price = plans[plan_code]
    subtotal = unit_price * quantity

    if promo_code is None or promo_code == "":
        discount_rate = 0.0
    elif promo_code == "SAVE10":
        discount_rate = 0.10
    elif promo_code == "CLOSENOW15":
        discount_rate = 0.15
    else:
        raise ValueError(f"Unauthorized promo code: {promo_code}")

    final_price = round(subtotal * (1.0 - discount_rate), 2)
    return final_price


def create_booking(sku_id: str, plan_code: str, quantity: int, promo_code: Optional[str], final_price: float, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    """
    POST API — Create the final booking after discussing with the user.
    Simulates ~1.2s network/gateway latency.
    Strictly validates business rules and discounts.
    """
    start_time = time.time()
    
    # 1. Validation check
    expected = calculate_expected_price(sku_id, plan_code, quantity, promo_code)
    if abs(final_price - expected) > 0.02:
        error_msg = f"Price mismatch: Received {final_price}, expected {expected} for {quantity}x {sku_id} ({plan_code}) with promo {promo_code}"
        duration_ms = round((time.time() - start_time) * 1000, 2)
        log_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "method": "POST",
            "endpoint": "/api/bookings",
            "payload": {
                "sku_id": sku_id,
                "plan_code": plan_code,
                "quantity": quantity,
                "promo_code": promo_code,
                "final_price": final_price,
                "idempotency_key": idempotency_key
            },
            "status_code": 400,
            "latency_ms": duration_ms,
            "error": error_msg
        }
        with _booking_lock:
            _booking_api_log.append(log_entry)
        raise ValueError(error_msg)

    # 2. Check idempotency if key provided
    if idempotency_key:
        with _booking_lock:
            for bk in _bookings_registry.values():
                if bk.get("idempotency_key") == idempotency_key:
                    # Return already booked record without reprocessing
                    return bk

    # 3. Simulate ~1.2 second processing latency
    time.sleep(BOOKING_API_LATENCY)

    # 4. Generate confirmed booking record
    booking_id = f"BK-{uuid.uuid4().hex[:8].upper()}"
    booking_record = {
        "booking_id": booking_id,
        "sku_id": sku_id,
        "product_name": CATALOG_DATA[sku_id]["name"],
        "plan_code": plan_code,
        "quantity": quantity,
        "promo_code": promo_code,
        "final_price": final_price,
        "status": "CONFIRMED",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "idempotency_key": idempotency_key
    }

    with _booking_lock:
        _bookings_registry[booking_id] = booking_record
        duration_ms = round((time.time() - start_time) * 1000, 2)
        _booking_api_log.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "method": "POST",
            "endpoint": "/api/bookings",
            "payload": {
                "sku_id": sku_id,
                "plan_code": plan_code,
                "quantity": quantity,
                "promo_code": promo_code,
                "final_price": final_price,
                "idempotency_key": idempotency_key
            },
            "status_code": 201,
            "latency_ms": duration_ms,
            "response": booking_record
        })

    return booking_record
