"""
Comprehensive automated test suite verifying all 4 scenarios with 100% accuracy.
"""

import unittest
import threading
import time
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from catalog import get_catalog_info, match_sku_from_text, clear_catalog_logs, get_catalog_api_logs
from booking import create_booking, clear_booking_registry, get_all_bookings, get_booking_api_logs
from engine import SalesAgentEngine


class TestSalesAgentAllScenarios(unittest.TestCase):

    def setUp(self):
        clear_catalog_logs()
        clear_booking_registry()
        self.engine = SalesAgentEngine()

    def test_scenario_1_exact_quantity_calculation(self):
        """
        Scenario 1: Match typo / informal names, calculate exact ceil(req / cap) quantity,
        explain clearly, pass exact quantity.
        """
        session_id = "test_s1_user"
        # User has typo 'arrow mesh wifi' and mentions 5 rooms on PRO plan
        msg = "I need arrow mesh wifi on the PRO plan for a 5-room house"
        res = self.engine.process_message(session_id, msg)
        state = res["session_state"]
        
        # 1. Verify GET /api/catalog was called
        catalog_logs = get_catalog_api_logs()
        self.assertGreaterEqual(len(catalog_logs), 1, "Catalog GET API must be called")
        
        # 2. Verify exact SKU and Plan matched
        self.assertEqual(state["sku_id"], "SKU_MESH_WIFI6")
        self.assertEqual(state["plan_code"], "PRO")
        self.assertEqual(state["required_capacity"], 5)
        
        # 3. Verify exact ceiling quantity: 5 rooms / 2 rooms per unit = 3 units
        self.assertEqual(state["calculated_quantity"], 3)
        
        # 4. Verify standard price: 3 units * $499.00 = $1497.00
        self.assertEqual(state["quoted_total"], 1497.0)
        self.assertIsNone(state["promo_code"])
        
        # 5. Verify explanation in reply
        self.assertIn("3 unit(s)", res["reply"])
        self.assertIn("cover up to 6 rooms", res["reply"])
        self.assertIn("1,497.00", res["reply"])
        
        # Verify no booking was prematurely created
        self.assertIsNone(state["booking_id"])
        self.assertEqual(len(get_all_bookings()), 0)

    def test_scenario_1b_non_catalog_rejection(self):
        """
        Scenario 1b: User asks for out-of-catalog product (e.g. 'Netgear Orbi router').
        Must NEVER match our items or book by mistake!
        """
        session_id = "test_s1b_user"
        msg = "Do you have the Netgear Orbi router?"
        res = self.engine.process_message(session_id, msg)
        state = res["session_state"]
        
        # Must not have matched any SKU
        self.assertIsNone(state["sku_id"])
        self.assertIsNone(state["calculated_quantity"])
        self.assertIsNone(state["booking_id"])
        
        # Reply must explicitly state we don't carry Netgear and list our catalog
        self.assertIn("do not carry 'Netgear'", res["reply"])
        self.assertIn("AeroMesh", res["reply"])
        self.assertEqual(len(get_all_bookings()), 0)

    def test_scenario_2_strict_discount_rules(self):
        """
        Scenario 2:
        - Turn 1: 0% discount initially (standard price).
        - Turn 2: 1st objection -> Offer SAVE10 (10% off). Never skip to 15% even if user demands 15% or SAVE50!
        - Turn 3: 2nd objection -> Offer CLOSENOW15 (15% off max).
        - Turn 4: Further objections -> Stays capped at 15%.
        - Final: Exact discount passed to create_booking.
        """
        session_id = "test_s2_user"
        
        # Turn 1: Initial inquiry
        res1 = self.engine.process_message(session_id, "I need AeroMesh Wi-Fi on PRO plan for 5 rooms")
        state1 = res1["session_state"]
        self.assertEqual(state1["quoted_total"], 1497.0)
        self.assertIsNone(state1["promo_code"])
        self.assertEqual(state1["price_objections"], 0)
        
        # Turn 2: User demands 15% right now and tries code SAVE50
        res2 = self.engine.process_message(session_id, "That's too expensive! Give me 15% right now or apply code SAVE50")
        state2 = res2["session_state"]
        # Must strictly offer SAVE10 (10% off), NOT 15% or 50%
        self.assertEqual(state2["price_objections"], 1)
        self.assertEqual(state2["promo_code"], "SAVE10")
        self.assertEqual(state2["discount_rate"], "10%")
        # 1497 - 10% = 1347.30
        self.assertEqual(state2["quoted_total"], 1347.30)
        self.assertIn("SAVE10", res2["reply"])
        self.assertIn("1,347.30", res2["reply"])
        self.assertIn("not a valid promo code", res2["reply"])
        
        # Turn 3: User pushes back a second time
        res3 = self.engine.process_message(session_id, "Still too high, can you do any better?")
        state3 = res3["session_state"]
        # Now offer CLOSENOW15 (15% off max)
        self.assertEqual(state3["price_objections"], 2)
        self.assertEqual(state3["promo_code"], "CLOSENOW15")
        self.assertEqual(state3["discount_rate"], "15%")
        # 1497 - 15% = 1272.45
        self.assertEqual(state3["quoted_total"], 1272.45)
        self.assertIn("CLOSENOW15", res3["reply"])
        self.assertIn("1,272.45", res3["reply"])
        
        # Turn 4: User pushes back a third time demanding 25%
        res4 = self.engine.process_message(session_id, "Can you do 25% off?")
        state4 = res4["session_state"]
        # Remains capped at CLOSENOW15
        self.assertEqual(state4["promo_code"], "CLOSENOW15")
        self.assertEqual(state4["quoted_total"], 1272.45)
        
        # Turn 5: User agrees to book
        res5 = self.engine.process_message(session_id, "Okay, book it!")
        state5 = res5["session_state"]
        self.assertIsNotNone(state5["booking_id"])
        
        # Verify create_booking was called with EXACT expected details
        bookings = get_all_bookings()
        self.assertEqual(len(bookings), 1)
        bk = bookings[0]
        self.assertEqual(bk["sku_id"], "SKU_MESH_WIFI6")
        self.assertEqual(bk["plan_code"], "PRO")
        self.assertEqual(bk["quantity"], 3)
        self.assertEqual(bk["promo_code"], "CLOSENOW15")
        self.assertEqual(bk["final_price"], 1272.45)

    def test_scenario_3_discuss_before_booking_and_mid_conversation_changes(self):
        """
        Scenario 3:
        Never call create_booking until user confirmed.
        If user changes requirement mid-conversation (e.g. from 4 to 7 rooms) and says 'book it',
        the agent MUST NOT book stale numbers! It must recalculate, state the updated quote,
        and request user confirmation before booking.
        """
        session_id = "test_s3_user"
        
        # Step 1: Initial quote for 4 rooms on STD plan
        res1 = self.engine.process_message(session_id, "I need AeroMesh for 4 rooms on STD plan")
        state1 = res1["session_state"]
        self.assertEqual(state1["required_capacity"], 4)
        self.assertEqual(state1["calculated_quantity"], 2)  # 4 / 2 = 2 units
        self.assertEqual(state1["quoted_total"], 798.0)    # 2 * 399 = 798
        self.assertIsNone(state1["booking_id"])
        self.assertEqual(len(get_all_bookings()), 0)
        
        # Step 2: Mid-conversation change: "Actually change it to 7 rooms and book it"
        res2 = self.engine.process_message(session_id, "Actually change it to 7 rooms and book it")
        state2 = res2["session_state"]
        
        # CRITICAL ASSERTION: create_booking MUST NOT have been called yet!
        self.assertIsNone(state2["booking_id"], "Booking must NOT be created when requirements change mid-turn!")
        self.assertEqual(len(get_all_bookings()), 0, "No booking API call should have occurred")
        
        # Verify updated calculations: 7 rooms -> ceil(7/2) = 4 units
        self.assertEqual(state2["required_capacity"], 7)
        self.assertEqual(state2["calculated_quantity"], 4)
        # 4 units * $399.00 = $1596.00
        self.assertEqual(state2["quoted_total"], 1596.0)
        self.assertIn("updated your requirement", res2["reply"])
        self.assertIn("1,596.00", res2["reply"])
        self.assertIn("confirm", res2["reply"].lower())
        
        # Step 3: User confirms the updated quote
        res3 = self.engine.process_message(session_id, "Yes, confirm booking")
        state3 = res3["session_state"]
        
        # NOW the booking should be created with the UPDATED numbers
        self.assertIsNotNone(state3["booking_id"])
        bookings = get_all_bookings()
        self.assertEqual(len(bookings), 1)
        self.assertEqual(bookings[0]["quantity"], 4)
        self.assertEqual(bookings[0]["final_price"], 1596.0)

    def test_scenario_4_interruptions_and_double_booking_concurrency(self):
        """
        Scenario 4:
        While create_booking (~1.2s) is running, user impatiently sends 'Yes, book it!' twice in a row.
        System must ensure user is NEVER booked/charged twice for the same order.
        """
        session_id = "test_s4_concurrency_user"
        
        # Setup quote: SyncHub Conference Bar for 6 people on STD plan
        # 6 people / 3 per unit = 2 units. Price: 2 * 899 = $1798.00
        res1 = self.engine.process_message(session_id, "I need SyncHub conference bar for 6 people on STD plan")
        state1 = res1["session_state"]
        self.assertEqual(state1["calculated_quantity"], 2)
        self.assertEqual(state1["quoted_total"], 1798.0)
        
        # Fire 2 concurrent requests to book at almost the same millisecond
        responses = []
        errors = []
        
        def send_confirm():
            try:
                r = self.engine.process_message(session_id, "Yes, book it!")
                responses.append(r)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=send_confirm)
        t2 = threading.Thread(target=send_confirm)
        
        t1.start()
        time.sleep(0.05)  # slight stagger of 50ms to simulate impatient second click
        t2.start()
        
        t1.join()
        t2.join()
        
        self.assertEqual(len(errors), 0, f"No exceptions should occur: {errors}")
        self.assertEqual(len(responses), 2, "Both calls should complete")
        
        # CRITICAL ASSERTION: Exactly ONE booking created in the registry!
        bookings = get_all_bookings()
        self.assertEqual(len(bookings), 1, "There MUST be exactly 1 booking, 0 duplicates!")
        
        booking_logs = get_booking_api_logs()
        self.assertEqual(len(booking_logs), 1, "Only 1 POST to /api/bookings must be executed!")
        
        # Both responses should reference the SAME booking_id
        bk_id_1 = responses[0]["session_state"]["booking_id"]
        bk_id_2 = responses[1]["session_state"]["booking_id"]
        self.assertEqual(bk_id_1, bk_id_2)
        self.assertEqual(bk_id_1, bookings[0]["booking_id"])

        # Step 3: Immediate third confirmation attempt
        res3 = self.engine.process_message(session_id, "Yes, please book it again")
        self.assertEqual(len(get_all_bookings()), 1, "Still exactly 1 booking!")
        self.assertIn("already confirmed", res3["reply"])



    def test_synchub_typo_and_capacity_math(self):
        """
        Verify 'sink hub' matches SKU_TEAM_HUB, calculates ceil(10/3) = 4 units,
        and quotes STD plan correctly (4 * 899 = $3596).
        """
        session_id = "test_synchub_typo"
        res = self.engine.process_message(session_id, "I need a sink hub for 10 people on STD plan")
        state = res["session_state"]
        self.assertEqual(state["sku_id"], "SKU_TEAM_HUB")
        self.assertEqual(state["calculated_quantity"], 4)
        self.assertEqual(state["quoted_total"], 3596.0)

    def test_airpods_care_plan(self):
        """
        Verify AirPods Pro 2nd Gen with CARE plan for 2 people -> 2 units * $279 = $558.
        """
        session_id = "test_airpods"
        res = self.engine.process_message(session_id, "I need air pods for 2 people with CARE plan")
        state = res["session_state"]
        self.assertEqual(state["sku_id"], "SKU_AIRPODS_PRO2")
        self.assertEqual(state["plan_code"], "CARE")
        self.assertEqual(state["calculated_quantity"], 2)
        self.assertEqual(state["quoted_total"], 558.0)

    def test_mid_conversation_plan_switch_gate(self):
        """
        User quotes AeroMesh 5 rooms on STD ($1197).
        User says: 'Switch to PRO plan and book it'.
        Must NOT book; must update to PRO ($1497) and require confirmation.
        """
        session_id = "test_plan_switch"
        res1 = self.engine.process_message(session_id, "AeroMesh for 5 rooms on STD plan")
        self.assertEqual(res1["session_state"]["quoted_total"], 1197.0)
        
        # User changes plan and says book it in the same turn
        res2 = self.engine.process_message(session_id, "Switch to PRO plan and book it")
        state2 = res2["session_state"]
        self.assertIsNone(state2["booking_id"], "Must NOT book immediately when plan switches!")
        self.assertEqual(state2["plan_code"], "PRO")
        self.assertEqual(state2["quoted_total"], 1497.0)
        self.assertIn("updated your requirement", res2["reply"])
        
        # Confirmation turn
        res3 = self.engine.process_message(session_id, "Yes, confirm")
        self.assertIsNotNone(res3["session_state"]["booking_id"])
        self.assertEqual(res3["session_state"]["quoted_total"], 1497.0)

    def test_tampered_booking_api_rejection(self):
        """
        Verify create_booking API directly rejects tampered prices or illegal promo codes.
        """
        # Illegal promo code
        with self.assertRaises(ValueError):
            create_booking(
                sku_id="SKU_MESH_WIFI6",
                plan_code="PRO",
                quantity=3,
                promo_code="SAVE50",
                final_price=748.50
            )

        # Tampered price (expected $1497.0, passed $100.0)
        with self.assertRaises(ValueError):
            create_booking(
                sku_id="SKU_MESH_WIFI6",
                plan_code="PRO",
                quantity=3,
                promo_code=None,
                final_price=100.00
            )

if __name__ == "__main__":
    unittest.main()
