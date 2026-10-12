"""Send received line items to the stock tracker (your Render app).

Contract - the tracker needs one endpoint:

    POST <stock_url>
    Authorization: Bearer <api key>
    Content-Type: application/json

    {
      "external_id": "094123456:4587",      # stable id - use it to ignore repeats
      "supplier": "ΙΣΧΥΣ_ΑΕ", "supplier_vat": "094123456",
      "invoice": "4587", "date": "2026-09-03", "mark": "",
      "total": 576.60,
      "items": [{"description": "...", "qty": 10, "unit": "τεμ",
                 "unit_price": 12.5, "amount": 125.0}]
    }

Any 2xx response = received. Failures stay queued and are retried.
"""
import json
import threading

from . import net


def payload(inv):
    items = json.loads(inv.get("items_json") or "[]")
    return {
        "external_id": f"{inv.get('supplier_vat') or inv['supplier_name']}:{inv['invoice_no']}",
        "supplier": inv["supplier_name"], "supplier_vat": inv.get("supplier_vat", ""),
        "invoice": inv["invoice_no"], "date": inv.get("invoice_date", ""), "mark": inv.get("mark", ""),
        "total": inv.get("total"), "items": items,
    }


def send(url, api_key, inv):
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    status, _ = net.request(url, "POST", headers=headers, data=payload(inv), timeout=30)
    return status


_FLUSH_LOCK = threading.Lock()


def flush(db, url, api_key):
    """Send every queued invoice. Returns (sent, failed, last_error). One run at a time."""
    with _FLUSH_LOCK:
        return _flush(db, url, api_key)


def _flush(db, url, api_key):
    sent = failed = 0
    last_error = ""
    for inv in db.pending_stock():
        try:
            send(url, api_key, inv)
            db.update_invoice(inv["id"], stock_status="sent", stock_error="")
            sent += 1
        except Exception as e:
            db.update_invoice(inv["id"], stock_status="failed", stock_error=str(e)[:300])
            failed += 1
            last_error = str(e)
            if isinstance(e, net.HttpError) and e.status == 0:
                break  # offline - try again later
    return sent, failed, last_error


def test(url, api_key):
    """Reachability check: any HTTP answer below 500 means the server is there."""
    try:
        net.request(url, "GET", headers={"Authorization": f"Bearer {api_key}"} if api_key else {}, timeout=15)
        return True, "Connected"
    except net.HttpError as e:
        if e.status and e.status < 500:
            return True, f"Server reachable (HTTP {e.status} on GET is fine - it only needs POST)"
        return False, str(e)
