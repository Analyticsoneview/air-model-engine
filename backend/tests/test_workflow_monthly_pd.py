from app.workflow_engine import WorkflowStore
import app.workflow_executor as executor

def test_monthly_pd_action_evaluates_and_persists_cycle_snapshot(tmp_path, monkeypatch):
    from app.air_monthly_pd_store import AirMonthlyPdStore
    monkeypatch.setenv("AIR_MONTHLY_PD_DB_PATH",str(tmp_path/"monthly.sqlite"))
    store=WorkflowStore(str(tmp_path/"workflow.sqlite"))
    try:
        workflow=store.create_workflow(name="MPD evaluator",created_by="admin",trigger_type="EVENT",
            trigger_config={"event_type":"mpd.trigger"},
            workflow_spec={"steps":[{"id":"evaluate","action":"monthly_pd.evaluate","params":{}}]})
        store.set_workflow_enabled(workflow["workflow_id"],True)
        event=store.publish_event(event_type="mpd.trigger",source="test",payload={
            "instrument_type":"EQUITY","symbol":"ABC","cycle_month":"2026-11",
            "reference_date":"2026-11-23","as_of_date":"2026-11-25",
            "previous_month_bars":[{"low":100,"high":130},{"low":95,"high":125}],
            "post_reference_bars":[{"date":"2026-11-24","low":101},{"date":"2026-11-25","low":100}],
            "structure_bars":[{"date":str(i),"close":100+i,"low":99+i,"high":101+i} for i in range(15)],
            "expiry_date":"2026-11-26","option_volume":100,"historical_volume_avg":100,
            "oi_change_pct":10,"premium_change_pct":8,"spread_pct":1,"underlying_volume_ratio":1.3
        },idempotency_key="mpd:test")
        run=store.process_event(event["event_id"])[0]
        result=executor.execute_workflow_run(store,run["run_id"])
        assert result["status"]=="SUCCEEDED"
        step=store.list_run_steps(run["run_id"])[0]
        assert step["output"]["status"]=="OPEN_FOR_BUY"
        assert step["output"]["persisted_snapshot"]["support_status"]=="OPEN_FOR_BUY"
        pd=AirMonthlyPdStore(str(tmp_path/"monthly.sqlite"))
        try:
            assert len(pd.list_cycles(symbol="ABC",cycle_month="2026-11"))==1
            assert len(pd.list_snapshots())==1
        finally: pd.close()
    finally: store.close()
