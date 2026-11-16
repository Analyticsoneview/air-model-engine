from app.air_monthly_pd_store import AirMonthlyPdStore

def test_cycle_and_snapshot_are_idempotent_and_history_is_retained(tmp_path):
    store=AirMonthlyPdStore(str(tmp_path/"mpd.sqlite"))
    try:
        first=store.save_cycle(instrument_type="EQUITY",symbol="ABC",cycle_month="2026-11",
            reference_date="2026-11-23",pml=100,pmh=140,eq=120)
        again=store.save_cycle(instrument_type="EQUITY",symbol="ABC",cycle_month="2026-11",
            reference_date="2026-11-23",pml=101,pmh=141,eq=121)
        assert first["cycle_id"]==again["cycle_id"]
        assert float(again["previous_month_pml"])==100
        snap=store.save_snapshot(cycle_id=first["cycle_id"],as_of_date="2026-11-25",
            snapshot_type="DAILY",support_status="OPEN_FOR_BUY",pattern="W",
            pattern_state="FORMING",evidence={"oi_change_pct":12},forecast={"target":150})
        snap2=store.save_snapshot(cycle_id=first["cycle_id"],as_of_date="2026-11-25",
            snapshot_type="DAILY",support_status="INVALIDATED",pattern="NONE",
            pattern_state="FAILED")
        assert snap["snapshot_id"]==snap2["snapshot_id"]
        assert snap2["support_status"]=="OPEN_FOR_BUY"
        store.save_cycle(instrument_type="EQUITY",symbol="ABC",cycle_month="2026-12",
            reference_date="2026-12-23",pml=110,pmh=150,eq=130)
        assert len(store.list_cycles(symbol="ABC"))==2
        assert store.list_snapshots(cycle_id=first["cycle_id"])[0]["evidence"]=={"oi_change_pct":12}
    finally:
        store.close()
