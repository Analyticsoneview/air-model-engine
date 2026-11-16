"""PostgreSQL/RLS acceptance for the commercial usage ledger."""
from __future__ import annotations
import os
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from app.tenant_context import tenant_scope
from app.usage_metering import UsageMeter, UsageQuotaExceeded


def _url():
    value=os.getenv("AIR_TEST_CUSTOMER_DATABASE_URL","")
    if not value:
        pytest.skip("AIR_TEST_CUSTOMER_DATABASE_URL not configured")
    if not value.startswith(("postgresql://","postgresql+psycopg://")):
        pytest.fail("AIR_TEST_CUSTOMER_DATABASE_URL must point to PostgreSQL")
    if "test" not in value.rsplit("/",1)[-1].lower():
        pytest.fail("Usage integration requires a disposable database with test in its name")
    return value


def _tenant(url):
    tenant=str(uuid4())
    engine=create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('air.is_admin','true',false)"))
        conn.execute(text("""INSERT INTO air_tenants
            (tenant_id,name,owner_customer_id,plan_code,status,storage_prefix,rabbitmq_vhost,
             max_members,max_api_calls_per_day,max_storage_bytes)
            VALUES(:id,:name,:owner,'STANDARD','ACTIVE',:prefix,:vhost,1,10000,1073741824)"""),
            {"id":tenant,"name":"Usage test "+tenant,"owner":"usage-"+tenant,
             "prefix":"usage-test/"+tenant+"/","vhost":"usage-"+tenant.replace("-","")})
    engine.dispose()
    return tenant


def test_usage_ledger_postgres_tenant_rls_idempotency_and_quota():
    url=_url()
    tenant=_tenant(url)
    customer="usage-customer-"+tenant
    meter=UsageMeter(database_url=url)
    with tenant_scope(is_admin=True):
        meter.set_quota_override(tenant,"api_calls","DAILY",soft_limit=1,hard_limit=2,actor_id="test-admin")
    first=meter.record_usage(tenant,customer,"api_calls",1,plan_code="B2C_FREE",idempotency_key="pg-usage-1")
    replay=meter.record_usage(tenant,customer,"api_calls",1,plan_code="B2C_FREE",idempotency_key="pg-usage-1")
    assert first["allowed"] and replay["idempotent_replay"]
    second=meter.record_usage(tenant,customer,"api_calls",1,plan_code="B2C_FREE",idempotency_key="pg-usage-2")
    assert second["allowed"] and second["soft_limit_exceeded"]
    with pytest.raises(UsageQuotaExceeded):
        meter.consume(tenant,customer,"api_calls",1,plan_code="B2C_FREE",idempotency_key="pg-usage-3")
    with tenant_scope(tenant_id=tenant,customer_id=customer):
        own=meter.get_usage(tenant,"B2C_FREE")
    with tenant_scope(tenant_id=str(uuid4()),customer_id="other-customer"):
        other=meter.get_usage(tenant,"B2C_FREE")
    api=next(item for item in own if item["metric"]=="api_calls")
    other_api=next(item for item in other if item["metric"]=="api_calls")
    assert api["used"]==2
    assert other_api["used"]==0
    meter.engine.dispose()
