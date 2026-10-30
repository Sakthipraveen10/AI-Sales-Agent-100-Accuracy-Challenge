"""
Flask Web Application & REST API for AI Sales Agent.
Exposes /api/catalog, /api/bookings, /api/chat, /api/logs, and an interactive Web Dashboard.
"""

import os
import uuid
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

from catalog import get_catalog_info, get_catalog_api_logs, clear_catalog_logs, CATALOG_DATA
from booking import create_booking, get_booking_api_logs, clear_booking_registry, get_all_bookings
from engine import SalesAgentEngine

app = Flask(__name__)
CORS(app)

engine = SalesAgentEngine()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/catalog", methods=["GET"])
def api_catalog():
    """
    Official GET API:
    Fetch available packages, max capacity per unit, plans, and prices.
    """
    query = request.args.get("query", "")
    data = get_catalog_info(query)
    return jsonify(data), 200


@app.route("/api/bookings", methods=["POST"])
def api_bookings():
    """
    Official POST API:
    Create final booking after discussing with the user.
    """
    body = request.get_json(force=True, silent=True) or {}
    sku_id = body.get("sku_id")
    plan_code = body.get("plan_code")
    quantity = body.get("quantity")
    promo_code = body.get("promo_code")
    final_price = body.get("final_price")

    if not sku_id or not plan_code or quantity is None or final_price is None:
        return jsonify({"error": "Missing required fields: sku_id, plan_code, quantity, final_price"}), 400

    try:
        booking = create_booking(
            sku_id=sku_id,
            plan_code=plan_code,
            quantity=int(quantity),
            promo_code=promo_code,
            final_price=float(final_price)
        )
        return jsonify(booking), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """
    Chatbot endpoint:
    Processes user turn, manages state, enforces guardrails, and returns reply & logs.
    """
    body = request.get_json(force=True, silent=True) or {}
    session_id = body.get("session_id") or str(uuid.uuid4())
    message = body.get("message", "").strip()

    if not message:
        return jsonify({"error": "Message cannot be empty"}), 400

    result = engine.process_message(session_id, message)
    
    # Include recent API logs in the response
    catalog_logs = get_catalog_api_logs()
    booking_logs = get_booking_api_logs()

    return jsonify({
        "session_id": session_id,
        "reply": result["reply"],
        "session_state": result["session_state"],
        "catalog_logs": catalog_logs[-5:],
        "booking_logs": booking_logs[-5:]
    }), 200


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Reset session state and optionally clear API logs."""
    body = request.get_json(force=True, silent=True) or {}
    session_id = body.get("session_id")
    if session_id:
        engine.reset_session(session_id)
    return jsonify({"status": "reset_successful", "session_id": session_id}), 200


@app.route("/api/logs", methods=["GET"])
def api_logs():
    """Return all audit logs for both GET catalog and POST booking APIs."""
    return jsonify({
        "catalog_api_logs": get_catalog_api_logs(),
        "booking_api_logs": get_booking_api_logs(),
        "total_bookings": get_all_bookings()
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print(f"🚀 AI Sales Agent server running at http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
