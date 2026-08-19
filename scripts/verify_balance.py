"""Deterministic verification gate for financial reconciliation (Zero-LLM)."""
import sys
import json
import math

def verify_reconciliation(payload: str) -> bool:
    """Verifies that Stripe payouts exactly equal QuickBooks bank ledger to the penny."""
    try:
        data = json.loads(payload)
        stripe_amount = float(data.get("stripe_total", 0.0))
        qbo_amount = float(data.get("qbo_total", 0.0))
        discrepancy = round(abs(stripe_amount - qbo_amount), 2)
        
        if discrepancy > 0.00:
            print(f"VERIFY FAILED: Balance mismatch of ${discrepancy:.2f}. Halting at gate.", file=sys.stderr)
            return False
            
        print(f"VERIFY PASSED: Perfect match (${stripe_amount:.2f} == ${qbo_amount:.2f}). 0 tokens consumed.")
        return True
    except Exception as e:
        print(f"VERIFY ERROR: Invalid payload: {e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    input_data = sys.argv[1] if len(sys.argv) > 1 else '{"stripe_total": 1450.00, "qbo_total": 1450.00}'
    ok = verify_reconciliation(input_data)
    sys.exit(0 if ok else 4)
