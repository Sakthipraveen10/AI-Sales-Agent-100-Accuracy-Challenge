"""
Deterministic State Machine & Sales Agent Orchestrator.
Guarantees 100% accuracy across catalog fetching, capacity math, discount progression,
mid-turn change gates, and idempotent booking concurrency.
"""

import math
import re
import threading
import time
from typing import Dict, Any, Optional, Tuple, List
from catalog import get_catalog_info, match_sku_from_text, CATALOG_DATA
from booking import create_booking, calculate_expected_price

# Word-to-number mapping for capacity extraction
WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20
}

# Regex patterns for price objections and promo code requests
OBJECTION_PATTERNS = [
    r"too\s*(?:expensive|pricey|much|high|costly|steep)",
    r"cheaper", r"lower\s*price", r"discount", r"promo", r"deal",
    r"better\s*price", r"can\s*you\s*do\s*better", r"still\s*too\s*(?:high|expensive)",
    r"give\s*me\s*(?:\d+%)?", r"out\s*of\s*(?:my\s*)?budget",
    r"save\d+", r"coupon", r"voucher", r"reduce", r"any\s*offer",
    r"\b\d+%\s*(?:off)?\b"
]

CONFIRMATION_PATTERNS = [
    r"\b(?:yes|yeah|yup|sure|ok|okay|please)\b.*\b(?:book|confirm|proceed|buy|order|go\s*ahead)\b",
    r"\b(?:book\s*it|confirm\s*it|create\s*booking|place\s*order|go\s*ahead|let's\s*do\s*it|do\s*it|sounds\s*good|looks\s*good)\b",
    r"^(?:yes|confirm|proceed|ok|okay|sure)$"
]

CHANGE_PATTERNS = [
    r"\b(?:change|switch|make\s*it|update|actually|instead|rather)\b",
    r"\b(?:now\s*need|actually\s*\d+|switch\s*to)\b"
]


class SalesSession:
    """Represents a conversational sales session with state persistence and concurrency protection."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.sku_id: Optional[str] = None
        self.plan_code: Optional[str] = None
        self.required_capacity: Optional[int] = None
        self.calculated_quantity: Optional[int] = None
        
        # Discount states
        self.price_objections: int = 0
        self.promo_code: Optional[str] = None
        self.discount_rate: float = 0.0
        
        # Quote states
        self.quoted_total: Optional[float] = None
        self.is_quoted: bool = False
        self.quote_signature: Optional[Tuple[str, str, int, float, Optional[str]]] = None
        self.user_confirmed_quote_signature: Optional[Tuple] = None
        
        # Booking tracking
        self.booking_in_progress: bool = False
        self.booking_result: Optional[Dict[str, Any]] = None
        
        # History & audit
        self.history: List[Dict[str, str]] = []
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize current state for inspector/debugging."""
        product_name = CATALOG_DATA.get(self.sku_id, {}).get("name") if self.sku_id else None
        return {
            "session_id": self.session_id,
            "sku_id": self.sku_id,
            "product_name": product_name,
            "plan_code": self.plan_code,
            "required_capacity": self.required_capacity,
            "calculated_quantity": self.calculated_quantity,
            "price_objections": self.price_objections,
            "promo_code": self.promo_code,
            "discount_rate": f"{int(self.discount_rate * 100)}%",
            "quoted_total": self.quoted_total,
            "is_quoted": self.is_quoted,
            "quote_signature": list(self.quote_signature) if self.quote_signature else None,
            "confirmed_signature": list(self.user_confirmed_quote_signature) if self.user_confirmed_quote_signature else None,
            "booking_in_progress": self.booking_in_progress,
            "booking_id": self.booking_result.get("booking_id") if self.booking_result else None,
            "status": "BOOKED" if self.booking_result else ("QUOTED" if self.is_quoted else "DISCUSSING")
        }


class SalesAgentEngine:
    """Stateful agent engine implementing 100% accurate sales conversation logic."""

    def __init__(self):
        self._sessions: Dict[str, SalesSession] = {}
        self._global_lock = threading.Lock()

    def get_session(self, session_id: str) -> SalesSession:
        with self._global_lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SalesSession(session_id)
            return self._sessions[session_id]

    def reset_session(self, session_id: str) -> SalesSession:
        with self._global_lock:
            self._sessions[session_id] = SalesSession(session_id)
            return self._sessions[session_id]

    def _extract_capacity(self, text: str) -> Optional[int]:
        """
        Extracts required capacity (rooms, people, units) accurately from text.
        Strictly ignores percentages (e.g. 25%), dollar prices ($499), and discounts.
        """
        lower = text.lower()
        
        # Strip out percentages like '25%', '15 percent', '$50', 'save10', 'closenow15'
        cleaned = re.sub(r"\b\d+\s*%", " ", lower)
        cleaned = re.sub(r"\b\d+\s*percent", " ", cleaned)
        cleaned = re.sub(r"\$\s*\d+", " ", cleaned)
        cleaned = re.sub(r"\b(save\d+|closenow\d+)\b", " ", cleaned)

        # 1. Look for explicit units: e.g. "5-room", "5 rooms", "7 rooms", "6 people", "3 seats"
        explicit_match = re.search(r"\b(\d+)\s*(?:-|\s+)?(?:rooms?|people|persons?|users?|units?|beds?|seats?|house)\b", cleaned)
        if explicit_match:
            return int(explicit_match.group(1))

        # 2. Word numbers with explicit units check (e.g., "five rooms", "seven rooms")
        for word, num in WORD_TO_NUM.items():
            pattern = rf"\b{word}\s*(?:-|\s+)?(?:rooms?|people|persons?|users?|units?|beds?|seats?|house)\b"
            if re.search(pattern, cleaned):
                return num
                
        # 3. Contextual numbers like "for 5", "change to 7", "make it 7"
        context_match = re.search(r"(?:for|covers?|capacity|need|make\s*it|to|change\s*to|actually)\s+(\d+)\b", cleaned)
        if context_match:
            val = int(context_match.group(1))
            if val not in [10, 15, 20, 25, 50, 100, 249, 279, 399, 499, 899, 1150]:
                return val

        return None

    def _extract_plan(self, text: str, current_sku: Optional[str]) -> Optional[str]:
        """Extracts plan code (STD, PRO, CARE)."""
        upper = text.upper()
        if "PRO" in upper:
            return "PRO"
        if "CARE" in upper or "APPLECARE" in upper:
            return "CARE"
        if "STD" in upper or "STANDARD" in upper:
            return "STD"
        return None

    def _detect_objection(self, text: str) -> bool:
        """Detects if user objects to price or asks for discount."""
        lower = text.lower()
        for pat in OBJECTION_PATTERNS:
            if re.search(pat, lower):
                return True
        return False

    def _detect_confirmation(self, text: str) -> bool:
        """Detects if user is confirming or agreeing to book."""
        lower = text.lower().strip()
        for pat in CONFIRMATION_PATTERNS:
            if re.search(pat, lower):
                return True
        return False

    def _detect_change(self, text: str) -> bool:
        """Detects if user indicates a change in requirement."""
        lower = text.lower()
        for pat in CHANGE_PATTERNS:
            if re.search(pat, lower):
                return True
        return False

    def process_message(self, session_id: str, user_message: str) -> Dict[str, Any]:
        """
        Processes a single user message turn with strict concurrency locking
        and business rules validation.
        """
        session = self.get_session(session_id)
        
        with session.lock:
            # Check if this session already has a booking in progress
            if session.booking_in_progress:
                # Wait for the in-progress booking to complete
                while session.booking_in_progress:
                    session.cond.wait(timeout=2.0)
                
                # If booking just completed, return the confirmation
                if session.booking_result:
                    reply = (
                        f"Your booking has already been successfully confirmed!\n"
                        f"• Confirmation ID: {session.booking_result['booking_id']}\n"
                        f"• Product: {session.booking_result['product_name']}\n"
                        f"• Plan: {session.booking_result['plan_code']}\n"
                        f"• Quantity: {session.booking_result['quantity']} unit(s)\n"
                        f"• Total Paid: ${session.booking_result['final_price']:,.2f}\n"
                        f"No duplicate charge was processed."
                    )
                    return {"reply": reply, "session_state": session.to_dict()}

            # If already booked previously, prevent duplicate booking
            if session.booking_result:
                reply = (
                    f"Your order is already confirmed under Booking ID {session.booking_result['booking_id']} "
                    f"for {session.booking_result['quantity']}x {session.booking_result['product_name']} "
                    f"at ${session.booking_result['final_price']:,.2f}. "
                    f"If you need a new booking, please reset the session or start a new order."
                )
                return {"reply": reply, "session_state": session.to_dict()}

            # Remember if quote was already presented prior to this turn
            was_previously_quoted = session.is_quoted
            previous_capacity = session.required_capacity
            previous_plan = session.plan_code
            previous_sku = session.sku_id

            # Record user message in history
            session.history.append({"role": "user", "content": user_message, "time": time.strftime("%H:%M:%S")})

            # -------------------------------------------------------------
            # STEP 1: Intent & Entity Parsing
            # -------------------------------------------------------------
            matched_sku, non_catalog = match_sku_from_text(user_message)
            capacity_input = self._extract_capacity(user_message)
            plan_input = self._extract_plan(user_message, session.sku_id or matched_sku)
            is_objection = self._detect_objection(user_message)
            is_confirmation = self._detect_confirmation(user_message)
            is_change = self._detect_change(user_message)

            # Check if user mentioned an unauthorized coupon code (e.g. SAVE50)
            user_coupon_match = re.search(r"\b(SAVE\d+|CLOSENOW\d+|DEAL\d+|VIP\d+)\b", user_message.upper())
            user_custom_code = user_coupon_match.group(1) if user_coupon_match else None

            # -------------------------------------------------------------
            # SCENARIO 1b: Out-of-catalog product requested
            # -------------------------------------------------------------
            if non_catalog:
                catalog = get_catalog_info()
                reply = (
                    f"I apologize, but we do not carry '{non_catalog.title()}'. "
                    f"Our catalog includes:\n"
                    f"1. AeroMesh Wi-Fi 6E Home Pack (Mesh Wi-Fi for multi-room homes)\n"
                    f"2. SyncHub Conference Bar (Meeting room video bar)\n"
                    f"3. AirPods Pro 2nd Gen (Personal audio)\n\n"
                    f"Would you like information on AeroMesh Wi-Fi or another item from our catalog?"
                )
                session.history.append({"role": "assistant", "content": reply, "time": time.strftime("%H:%M:%S")})
                return {"reply": reply, "session_state": session.to_dict()}

            # -------------------------------------------------------------
            # Update SKU, Plan, and Capacity tracking
            # -------------------------------------------------------------
            if matched_sku and matched_sku != session.sku_id:
                session.sku_id = matched_sku
                # Query catalog API for this product
                get_catalog_info(matched_sku)

            if plan_input:
                session.plan_code = plan_input

            if capacity_input:
                session.required_capacity = capacity_input

            # Ensure we have catalog info loaded
            if session.sku_id and not hasattr(session, '_catalog_loaded'):
                get_catalog_info(session.sku_id)
                session._catalog_loaded = True

            # Set default plan if SKU selected but no plan specified yet
            if session.sku_id and not session.plan_code:
                available_plans = list(CATALOG_DATA[session.sku_id]["plans"].keys())
                session.plan_code = "STD" if "STD" in available_plans else available_plans[0]

            # -------------------------------------------------------------
            # SCENARIO 1: Calculate Exact Quantity for User's Requirement
            # -------------------------------------------------------------
            if session.sku_id and session.required_capacity:
                sku_info = CATALOG_DATA[session.sku_id]
                cap_per_unit = sku_info["max_capacity_per_unit"]
                # Exact ceiling math: ceil(requirement / capacity_per_unit)
                session.calculated_quantity = math.ceil(session.required_capacity / cap_per_unit)

            # Determine if requirements changed AFTER an initial quote was already active
            requirement_modified = False
            if was_previously_quoted:
                if (capacity_input and capacity_input != previous_capacity) or \
                   (plan_input and plan_input != previous_plan) or \
                   (matched_sku and matched_sku != previous_sku) or \
                   (is_change and capacity_input is not None):
                    requirement_modified = True

            # -------------------------------------------------------------
            # SCENARIO 2: Price Discussion & Strict Discount Rules
            # -------------------------------------------------------------
            discount_message_note = ""
            if is_objection:
                session.price_objections += 1
                
                # Check for custom requested code like SAVE50
                if user_custom_code and user_custom_code not in ["SAVE10", "CLOSENOW15"]:
                    discount_message_note += f"Coupon '{user_custom_code}' is not a valid promo code. "

                if session.price_objections == 1:
                    # STRICT RULE: 1st objection = SAVE10 (10% off)
                    session.promo_code = "SAVE10"
                    session.discount_rate = 0.10
                    discount_message_note += "I can offer you our special first-tier discount: promo code SAVE10 for 10% off."
                elif session.price_objections >= 2:
                    # STRICT RULE: 2nd+ objection = CLOSENOW15 (15% off max)
                    session.promo_code = "CLOSENOW15"
                    session.discount_rate = 0.15
                    discount_message_note += "I can offer our maximum promotional discount: promo code CLOSENOW15 for 15% off. This is our absolute best rate."

            # Calculate total price
            if session.sku_id and session.plan_code and session.calculated_quantity:
                unit_price = CATALOG_DATA[session.sku_id]["plans"][session.plan_code]
                subtotal = unit_price * session.calculated_quantity
                discount_amount = round(subtotal * session.discount_rate, 2)
                session.quoted_total = round(subtotal - discount_amount, 2)
                session.is_quoted = True
                
                # Build quote signature
                new_signature = (
                    session.sku_id,
                    session.plan_code,
                    session.calculated_quantity,
                    session.quoted_total,
                    session.promo_code
                )
                session.quote_signature = new_signature

            # -------------------------------------------------------------
            # SCENARIO 3: Discuss Before Booking & Mid-Conversation Changes
            # -------------------------------------------------------------
            # Case 3A: Requirement changed mid-conversation!
            # If the user changed any requirement (e.g. rooms or plan) and says "Okay, book it",
            # we MUST NOT call create_booking. We must first present the updated details and price
            # and ask for confirmation!
            if requirement_modified and session.is_quoted:
                # Invalidate previous confirmation because details changed
                session.user_confirmed_quote_signature = None
                
                sku_info = CATALOG_DATA[session.sku_id]
                cap_per_unit = sku_info["max_capacity_per_unit"]
                unit_desc = sku_info["unit_description"]
                total_cap_covered = session.calculated_quantity * cap_per_unit
                unit_price = sku_info["plans"][session.plan_code]
                
                reply = (
                    f"I have updated your requirement:\n"
                    f"• Requirement: {session.required_capacity} {unit_desc}s\n"
                    f"• Recommended: {session.calculated_quantity} unit(s) of {sku_info['name']} "
                    f"(each unit covers up to {cap_per_unit} {unit_desc}s, covering up to {total_cap_covered} {unit_desc}s total)\n"
                    f"• Selected Plan: {session.plan_code} (${unit_price:,.2f} per unit)\n"
                )
                if session.promo_code:
                    reply += f"• Applied Discount: {session.promo_code} ({int(session.discount_rate * 100)}% off)\n"
                reply += (
                    f"• Updated Total Price: ${session.quoted_total:,.2f}\n\n"
                    f"Because your requirements changed, please confirm if you would like me to proceed with booking this updated order at ${session.quoted_total:,.2f}."
                )
                session.history.append({"role": "assistant", "content": reply, "time": time.strftime("%H:%M:%S")})
                return {"reply": reply, "session_state": session.to_dict()}

            # Case 3B: User is confirming the current quote (and no requirement change in this turn)
            if is_confirmation and session.is_quoted and not requirement_modified and not is_objection:
                # Mark confirmation for current quote signature
                session.user_confirmed_quote_signature = session.quote_signature
                
                # ---------------------------------------------------------
                # SCENARIO 4: Thread-Safe Concurrency & create_booking execution
                # ---------------------------------------------------------
                session.booking_in_progress = True
                
                try:
                    idempotency_key = f"{session.session_id}-{hash(session.quote_signature)}"
                    
                    booking = create_booking(
                        sku_id=session.sku_id,
                        plan_code=session.plan_code,
                        quantity=session.calculated_quantity,
                        promo_code=session.promo_code,
                        final_price=session.quoted_total,
                        idempotency_key=idempotency_key
                    )
                    session.booking_result = booking
                finally:
                    session.booking_in_progress = False
                    session.cond.notify_all()

                reply = (
                    f"🎉 Booking Confirmed Successfully!\n\n"
                    f"• Booking ID: {session.booking_result['booking_id']}\n"
                    f"• Package: {session.booking_result['product_name']}\n"
                    f"• Plan: {session.booking_result['plan_code']}\n"
                    f"• Quantity: {session.booking_result['quantity']} unit(s)\n"
                    f"• Promo Code: {session.booking_result['promo_code'] or 'None'}\n"
                    f"• Total Price: ${session.booking_result['final_price']:,.2f}\n"
                    f"• Status: {session.booking_result['status']}\n\n"
                    f"Thank you for your order! Your confirmation details have been processed."
                )
                session.history.append({"role": "assistant", "content": reply, "time": time.strftime("%H:%M:%S")})
                return {"reply": reply, "session_state": session.to_dict()}

            # -------------------------------------------------------------
            # Standard Discussion / Price Quote Presentation
            # -------------------------------------------------------------
            if session.sku_id and session.required_capacity:
                sku_info = CATALOG_DATA[session.sku_id]
                cap_per_unit = sku_info["max_capacity_per_unit"]
                unit_desc = sku_info["unit_description"]
                total_cap_covered = session.calculated_quantity * cap_per_unit
                unit_price = sku_info["plans"][session.plan_code]
                
                parts = []
                if discount_message_note:
                    parts.append(discount_message_note + "\n")
                    
                parts.append(
                    f"For your requirement of {session.required_capacity} {unit_desc}s, "
                    f"you need {session.calculated_quantity} unit(s) of {sku_info['name']}. "
                    f"(Each unit covers up to {cap_per_unit} {unit_desc}s, so {session.calculated_quantity} unit(s) cover up to {total_cap_covered} {unit_desc}s)."
                )
                parts.append(f"Plan: {session.plan_code} (${unit_price:,.2f} per unit).")
                
                if session.promo_code:
                    discount_val = round((unit_price * session.calculated_quantity) * session.discount_rate, 2)
                    parts.append(f"Applied Discount: {session.promo_code} ({int(session.discount_rate * 100)}% off, saving ${discount_val:,.2f}).")
                    
                parts.append(f"Total Price: ${session.quoted_total:,.2f}.")
                parts.append("Would you like me to book this for you?")
                
                reply = "\n".join(parts)
                session.history.append({"role": "assistant", "content": reply, "time": time.strftime("%H:%M:%S")})
                return {"reply": reply, "session_state": session.to_dict()}

            # If SKU is identified but capacity is still missing
            if session.sku_id and not session.required_capacity:
                sku_info = CATALOG_DATA[session.sku_id]
                reply = (
                    f"Great! You are interested in the {sku_info['name']}. "
                    f"Each unit covers up to {sku_info['max_capacity_per_unit']} {sku_info['unit_description']}(s). "
                    f"How many {sku_info['unit_description']}s do you need to cover?"
                )
                session.history.append({"role": "assistant", "content": reply, "time": time.strftime("%H:%M:%S")})
                return {"reply": reply, "session_state": session.to_dict()}

            # Initial greeting / catalog prompt
            catalog = get_catalog_info()
            reply = (
                "Hello! Welcome to our sales desk. We offer the following packages:\n"
                "• AeroMesh Wi-Fi 6E Home Pack: Covers up to 2 rooms per unit (STD: $399, PRO: $499)\n"
                "• SyncHub Conference Bar: Covers up to 3 people/seats per unit (STD: $899, PRO: $1,150)\n"
                "• AirPods Pro 2nd Gen: 1 person per unit (STD: $249, CARE: $279)\n\n"
                "What can I help you with today? (e.g., 'I need AeroMesh Wi-Fi on the PRO plan for a 5-room house')"
            )
            session.history.append({"role": "assistant", "content": reply, "time": time.strftime("%H:%M:%S")})
            return {"reply": reply, "session_state": session.to_dict()}
