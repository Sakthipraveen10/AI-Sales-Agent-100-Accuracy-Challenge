"""
Interactive CLI for AI Sales Agent.
Allows testing conversation turns with live state inspection and API call logging.
"""

import sys
import uuid
import json
from engine import SalesAgentEngine
from catalog import get_catalog_api_logs
from booking import get_booking_api_logs

# ANSI colors
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def print_banner():
    print(f"\n{CYAN}{BOLD}================================================================={RESET}")
    print(f"{CYAN}{BOLD}       AI Sales Agent — 100% Accuracy Challenge CLI             {RESET}")
    print(f"{CYAN}{BOLD}================================================================={RESET}")
    print(f"{DIM}Commands: 'state' (view session), 'logs' (view API logs), 'reset', 'quit'{RESET}\n")


def display_api_logs(last_count_catalog: int, last_count_booking: int):
    cat_logs = get_catalog_api_logs()
    bk_logs = get_booking_api_logs()
    
    new_cat = cat_logs[last_count_catalog:]
    new_bk = bk_logs[last_count_booking:]
    
    for l in new_cat:
        print(f"  {MAGENTA}[API CALL] GET /api/catalog | Latency: {l['latency_ms']}ms | Status: 200{RESET}")
    for l in new_bk:
        status_color = GREEN if l['status_code'] == 201 else RED
        print(f"  {YELLOW}{BOLD}[API CALL] POST /api/bookings | Latency: {l['latency_ms']}ms | Status: {l['status_code']}{RESET}")
        print(f"    {DIM}Payload: {json.dumps(l['payload'])}{RESET}")
        if 'response' in l:
            print(f"    {status_color}Response: Booking ID {l['response']['booking_id']} confirmed!{RESET}")
        elif 'error' in l:
            print(f"    {RED}Error: {l['error']}{RESET}")

    return len(cat_logs), len(bk_logs)


def main():
    print_banner()
    engine = SalesAgentEngine()
    session_id = f"cli_{uuid.uuid4().hex[:6]}"
    cat_count = 0
    bk_count = 0

    # Initial greeting
    res = engine.process_message(session_id, "hello")
    print(f"{GREEN}{BOLD}Bot:{RESET} {res['reply']}\n")
    cat_count, bk_count = display_api_logs(cat_count, bk_count)

    while True:
        try:
            user_input = input(f"{BOLD}You > {RESET}").strip()
            if not user_input:
                continue
            if user_input.lower() in ["quit", "exit", "q"]:
                print(f"\n{CYAN}Goodbye!{RESET}\n")
                break
            if user_input.lower() == "reset":
                session_id = f"cli_{uuid.uuid4().hex[:6]}"
                print(f"\n{YELLOW}[Session reset. New session: {session_id}]{RESET}\n")
                continue
            if user_input.lower() == "state":
                state = engine.get_session(session_id).to_dict()
                print(f"\n{CYAN}--- Current Session State ---{RESET}")
                for k, v in state.items():
                    print(f"  {BOLD}{k}:{RESET} {v}")
                print(f"{CYAN}----------------------------{RESET}\n")
                continue
            if user_input.lower() == "logs":
                print(f"\n{MAGENTA}--- Catalog GET API Logs ---{RESET}")
                for l in get_catalog_api_logs():
                    print(f"  {l['timestamp']} | {l['method']} {l['endpoint']} | {l['latency_ms']}ms")
                print(f"\n{YELLOW}--- Booking POST API Logs ---{RESET}")
                for l in get_booking_api_logs():
                    print(f"  {l['timestamp']} | POST /api/bookings | Status {l['status_code']} | {l['latency_ms']}ms")
                    print(f"    Payload: {l['payload']}")
                print()
                continue

            # Process turn
            res = engine.process_message(session_id, user_input)
            cat_count, bk_count = display_api_logs(cat_count, bk_count)
            print(f"\n{GREEN}{BOLD}Bot:{RESET} {res['reply']}\n")

        except (KeyboardInterrupt, EOFError):
            print(f"\n{CYAN}Exiting...{RESET}\n")
            break


if __name__ == "__main__":
    main()
