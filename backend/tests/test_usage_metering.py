from datetime import datetime, timezone
import pytest
from app.usage_metering import UsageMeter, UsageQuotaExceeded, UnknownUsagePlan, usage_period

def meter(tmp_path): return UsageMeter(database_url="",sqlite_path=str(tmp_path/"usage.sqlite3"))
def record(store,tenant="t1",metric="api_calls",quantity=1,key="e1",plan="B2C_FREE",now=None):
    return store.record_usage(tenant,"customer-1",metric,quantity,plan_code=plan,idempotency_key=key,now=now)

def test_period_boundaries_daily_monthly_annual():
    now=datetime(2026,12,31,23,59,tzinfo=timezone.utc)
    assert usage_period("DAILY",now)==(datetime(2026,12,31).date(),datetime(2027,1,1).date())
    assert usage_period("MONTHLY",now)==(datetime(2026,12,1).date(),datetime(2027,1,1).date())
    assert usage_period("ANNUAL",now)==(datetime(2026,1,1).date(),datetime(2027,1,1).date())

def test_idempotency_does_not_double_count(tmp_path):
    store=meter(tmp_path); first=record(store,key="same"); replay=record(store,key="same")
    assert first["allowed"] and replay["idempotent_replay"]
    assert store.get_usage("t1","B2C_FREE")[0]["used"]==1

def test_hard_quota_rejects_and_does_not_count_overage(tmp_path):
    store=meter(tmp_path)
    store.set_quota_override("t1","api_calls","DAILY",soft_limit=1,hard_limit=2,actor_id="admin")
    assert record(store,key="one")["allowed"] and record(store,key="two")["allowed"]
    rejected=record(store,key="three")
    assert not rejected["allowed"] and rejected["status"]=="REJECTED"
    assert store.get_usage("t1","B2C_FREE")[0]["used"]==2
    with pytest.raises(UsageQuotaExceeded):
        store.consume("t1","customer-1","api_calls",1,plan_code="B2C_FREE",idempotency_key="four")

def test_soft_limit_warns_without_blocking(tmp_path):
    store=meter(tmp_path); store.set_quota_override("t1","api_calls","DAILY",soft_limit=1,hard_limit=3,actor_id="admin")
    record(store,key="one"); result=record(store,key="two")
    assert result["allowed"] and result["soft_limit_exceeded"]

def test_tenant_isolation_and_period_rollover(tmp_path):
    store=meter(tmp_path); day1=datetime(2026,11,16,23,59,tzinfo=timezone.utc); day2=datetime(2026,11,17,0,1,tzinfo=timezone.utc)
    record(store,tenant="tenant-a",key="a1",now=day1); record(store,tenant="tenant-b",key="b1",now=day1)
    record(store,tenant="tenant-a",key="a2",now=day2)
    assert store.get_usage("tenant-a","B2C_FREE",day1)[0]["used"]==1
    assert store.get_usage("tenant-a","B2C_FREE",day2)[0]["used"]==1
    assert store.get_usage("tenant-b","B2C_FREE",day1)[0]["used"]==1

def test_unknown_plan_fails_closed(tmp_path):
    with pytest.raises(UnknownUsagePlan): record(meter(tmp_path),plan="UNRECOGNISED")

def test_negative_quantity_and_unknown_metric_rejected(tmp_path):
    store=meter(tmp_path)
    with pytest.raises(ValueError): record(store,quantity=-1)
    with pytest.raises(ValueError):
        store.record_usage("t1","c1","unknown",1,plan_code="B2C_FREE",idempotency_key="x")

def test_admin_custom_quota_override_is_validated(tmp_path):
    store=meter(tmp_path)
    with pytest.raises(ValueError):
        store.set_quota_override("t1","api_calls","DAILY",soft_limit=10,hard_limit=5,actor_id="admin")
    result=store.set_quota_override("t1","api_calls","DAILY",soft_limit=4,hard_limit=8,actor_id="admin")
    assert result["hard_limit"]==8 and store.get_usage("t1","B2C_FREE")[0]["hard_limit"]==8

def test_all_supported_metrics_have_plan_quotas(tmp_path):
    rows=meter(tmp_path).get_usage("t1","B2C_FREE")
    assert {row["metric"] for row in rows}=={"api_calls","compute_seconds","storage_bytes","seats","licensed_data_bytes"}

def test_adjustment_is_audited_idempotent_and_cannot_make_usage_negative(tmp_path):
    store=meter(tmp_path)
    record(store,key="seed")
    adjusted=store.adjust_usage("t1","customer-1","api_calls",-1,plan_code="B2C_FREE",
        idempotency_key="adjust-1",actor_id="admin-1",reason="Correct duplicate import")
    replay=store.adjust_usage("t1","customer-1","api_calls",-1,plan_code="B2C_FREE",
        idempotency_key="adjust-1",actor_id="admin-1",reason="Correct duplicate import")
    assert adjusted["used"]==0 and replay["idempotent_replay"]
    with pytest.raises(ValueError):
        store.adjust_usage("t1","customer-1","api_calls",-1,plan_code="B2C_FREE",
            idempotency_key="adjust-2",actor_id="admin-1",reason="Over correction")

def test_idempotency_key_cannot_be_reused_for_different_quantity(tmp_path):
    store=meter(tmp_path)
    record(store,key="same-key",quantity=1)
    with pytest.raises(ValueError):
        record(store,key="same-key",quantity=2)


def test_concurrent_usage_never_exceeds_hard_limit(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store=meter(tmp_path)
    store.set_quota_override("t1","api_calls","DAILY",soft_limit=3,hard_limit=5,actor_id="admin")
    def consume(index):
        return record(store,key=f"parallel-{index}")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(consume,range(12)))
    assert sum(1 for result in results if result["allowed"])==5
    assert store.get_usage("t1","B2C_FREE")[0]["used"]==5
