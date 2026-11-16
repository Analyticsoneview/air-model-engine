import pytest

from app.billing import BillingStore, BillingConflict


def store(tmp_path):
    return BillingStore(database_url="", sqlite_path=str(tmp_path / "billing.sqlite3"))


def create(store_, key="invoice-1", number="AIR-INV-001"):
    return store_.create_invoice("tenant-a", "customer-a", number, "INR", [
        {"description":"Annual AIR licence","quantity":2,"unit_amount_minor":10000,
         "tax_breakdown":[{"name":"GST","code":"GST","amount_minor":3600},
                          {"name":"CESS","code":"CESS","amount_minor":0}]},
        {"description":"Onboarding","quantity":1,"unit_amount_minor":5000,"tax_breakdown":[]},
    ], key, "customer-a")


def test_invoice_totals_use_explicit_tax_amounts_and_minor_units(tmp_path):
    billing=store(tmp_path)
    invoice=create(billing)
    assert invoice["subtotal_minor"]==25000
    assert invoice["tax_total_minor"]==3600
    assert invoice["total_minor"]==28600
    assert invoice["currency"]=="INR"
    assert invoice["status"]=="DRAFT"


def test_invoice_idempotency_and_tenant_isolation(tmp_path):
    billing=store(tmp_path)
    first=create(billing)
    replay=create(billing)
    assert first["invoice_id"]==replay["invoice_id"]
    assert replay["idempotent_replay"]
    assert billing.get_invoice("tenant-b",first["invoice_id"]) is None
    with pytest.raises(BillingConflict):
        create(billing,key="invoice-1",number="DIFFERENT")


def test_invoice_idempotency_is_stable_when_database_returns_lines_in_different_order(tmp_path):
    billing=store(tmp_path)
    lines=[
        {"description":"Zulu service","quantity":1,"unit_amount_minor":200,"tax_breakdown":[]},
        {"description":"Alpha service","quantity":2,"unit_amount_minor":100,"tax_breakdown":[]},
    ]
    first=billing.create_invoice("tenant-a","customer-a","ORDER-1","INR",lines,"order-key","customer-a")
    replay=billing.create_invoice("tenant-a","customer-a","ORDER-1","INR",list(reversed(lines)),"order-key","customer-a")
    assert first["invoice_id"]==replay["invoice_id"]
    assert replay["idempotent_replay"]


def test_invoice_requires_explicit_valid_tax_breakdown(tmp_path):
    billing=store(tmp_path)
    with pytest.raises(ValueError):
        billing.create_invoice("t","c","I-1","INR",[
            {"description":"x","quantity":1,"unit_amount_minor":100,
             "tax_breakdown":[{"name":"GST","code":"GST","amount_minor":-1}]}
        ],"k","c")


def test_issue_invoice_is_idempotent_and_audited(tmp_path):
    billing=store(tmp_path)
    invoice=create(billing)
    issued=billing.issue_invoice("tenant-a",invoice["invoice_id"],"customer-a","issue-1")
    replay=billing.issue_invoice("tenant-a",invoice["invoice_id"],"customer-a","issue-2")
    assert issued["status"]=="ISSUED"
    assert replay["idempotent_replay"]
    events=billing.audit_events("tenant-a","INVOICE",invoice["invoice_id"])
    assert [event["event_type"] for event in events]==["INVOICE_CREATED","INVOICE_ISSUED"]


def test_partial_refunds_create_credit_notes_and_cannot_exceed_invoice_total(tmp_path):
    billing=store(tmp_path)
    invoice=create(billing)
    billing.issue_invoice("tenant-a",invoice["invoice_id"],"customer-a","issue-1")
    first=billing.refund_invoice("tenant-a",invoice["invoice_id"],10000,"Partial credit","admin","refund-1")
    second=billing.refund_invoice("tenant-a",invoice["invoice_id"],18600,"Final credit","admin","refund-2")
    assert first["status"]=="RECORDED" and first["credit_note_number"].startswith("CN-")
    assert second["amount_minor"]==18600
    with pytest.raises(BillingConflict):
        billing.refund_invoice("tenant-a",invoice["invoice_id"],1,"Over refund","admin","refund-3")


def test_refund_idempotency_rejects_changed_amount(tmp_path):
    billing=store(tmp_path)
    invoice=create(billing)
    billing.issue_invoice("tenant-a",invoice["invoice_id"],"customer-a","issue-1")
    first=billing.refund_invoice("tenant-a",invoice["invoice_id"],100,"Correction","admin","same")
    replay=billing.refund_invoice("tenant-a",invoice["invoice_id"],100,"Correction","admin","same")
    assert first["refund_id"]==replay["refund_id"]
    with pytest.raises(BillingConflict):
        billing.refund_invoice("tenant-a",invoice["invoice_id"],101,"Correction","admin","same")


def test_settlement_provider_reference_and_reconciliation_status(tmp_path):
    billing=store(tmp_path)
    settlement=billing.record_settlement("tenant-a","sandbox","settle-1","INR",28600)
    duplicate=billing.record_settlement("tenant-a","sandbox","settle-1","INR",28600)
    assert duplicate["status"]=="DUPLICATE"
    match=billing.reconcile_settlement("tenant-a",settlement["settlement_id"],28600,"admin","recon-1")
    mismatch=billing.reconcile_settlement("tenant-a",settlement["settlement_id"],28000,"admin","recon-2","bank shortfall")
    assert match["status"]=="MATCH" and match["difference_minor"]==0
    assert mismatch["status"]=="MISMATCH" and mismatch["difference_minor"]==600


def test_settlement_duplicate_reference_with_changed_amount_is_conflict(tmp_path):
    billing=store(tmp_path)
    billing.record_settlement("tenant-a","sandbox","settle-1","INR",1000)
    with pytest.raises(BillingConflict):
        billing.record_settlement("tenant-a","sandbox","settle-1","INR",1001)


def test_reconciliation_idempotency_and_audit(tmp_path):
    billing=store(tmp_path)
    settlement=billing.record_settlement("tenant-a","sandbox","settle-1","INR",1000)
    first=billing.reconcile_settlement("tenant-a",settlement["settlement_id"],1000,"admin","recon")
    replay=billing.reconcile_settlement("tenant-a",settlement["settlement_id"],1000,"admin","recon")
    assert replay["idempotent_replay"]
    assert first["reconciliation_id"]==replay["reconciliation_id"]
    assert billing.audit_events("tenant-a","RECONCILIATION",first["reconciliation_id"])


def test_invoice_lists_are_bounded_and_tenant_scoped(tmp_path):
    billing=store(tmp_path)
    create(billing,key="a",number="A")
    billing.create_invoice("tenant-b","customer-b","B","USD",[
        {"description":"Service","quantity":1,"unit_amount_minor":100,"tax_breakdown":[]}
    ],"b","customer-b")
    assert len(billing.list_invoices("tenant-a",limit=1000))==1
    assert billing.list_invoices("tenant-a")[0]["invoice_number"]=="A"
