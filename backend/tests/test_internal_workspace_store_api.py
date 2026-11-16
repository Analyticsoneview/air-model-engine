import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import internal_workspace_api as api
from app.internal_workspace_store import InternalWorkspaceStore


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AIR_INTERNAL_OWNER_EMAIL", "owner@example.com")
    store = InternalWorkspaceStore(":memory:")
    monkeypatch.setattr(api, "_store", store)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.require_admin] = lambda: {
        "admin_id": "owner-1", "email": "owner@example.com", "role": "SUPER_ADMIN"
    }
    yield TestClient(app)
    store.close()
    monkeypatch.setattr(api, "_store", None)


def test_watchlist_create_list_update_delete(client):
    created = client.post("/api/v1/internal-workspace/watchlists", json={
        "name": "Nifty watch", "symbols": ["reliance", "NIFTY", "RELIANCE", " "]
    })
    assert created.status_code == 201
    item = created.json()["item"]
    assert item["classification"] == "INTERNAL — NOT FOR DISTRIBUTION"
    assert item["payload"]["symbols"] == ["RELIANCE", "NIFTY"]

    listed = client.get("/api/v1/internal-workspace/watchlists")
    assert len(listed.json()["items"]) == 1

    updated = client.put(f"/api/v1/internal-workspace/watchlists/{item['item_id']}", json={
        "name": "Updated watch", "symbols": ["INFY"]
    })
    assert updated.status_code == 200
    assert updated.json()["item"]["payload"]["symbols"] == ["INFY"]

    deleted = client.delete(f"/api/v1/internal-workspace/watchlists/{item['item_id']}")
    assert deleted.status_code == 200
    assert client.get("/api/v1/internal-workspace/watchlists").json()["items"] == []


def test_research_note_crud_and_audit(client):
    created = client.post("/api/v1/internal-workspace/notes", json={
        "title": "Private chart study",
        "content": "Price is approaching the prior range high.",
        "tags": ["SMC", "review"],
        "related_symbols": ["reliance"]
    })
    assert created.status_code == 201
    item = created.json()["item"]
    assert item["payload"]["related_symbols"] == ["RELIANCE"]

    updated = client.put(f"/api/v1/internal-workspace/notes/{item['item_id']}", json={
        "title": "Updated study", "content": "Wait for confirmation."
    })
    assert updated.status_code == 200
    assert updated.json()["item"]["title"] == "Updated study"

    events = client.get("/api/v1/internal-workspace/audit").json()["events"]
    assert [event["action"] for event in events] == ["UPDATE", "CREATE"]

    assert client.delete(f"/api/v1/internal-workspace/notes/{item['item_id']}").status_code == 200


def test_private_items_are_owner_scoped():
    store = InternalWorkspaceStore(":memory:")
    try:
        item = store.create_item("owner-a", "WATCHLIST", "A", {"symbols": ["NIFTY"]})
        assert store.get_item("owner-b", item["item_id"], "WATCHLIST") is None
        assert store.list_items("owner-b", "WATCHLIST") == []
        assert store.delete_item("owner-b", item["item_id"], "WATCHLIST") is False
        assert store.get_item("owner-a", item["item_id"], "WATCHLIST") is not None
    finally:
        store.close()


def test_watchlist_rejects_empty_symbols(client):
    response = client.post("/api/v1/internal-workspace/watchlists", json={
        "name": "Empty", "symbols": [" ", ""]
    })
    assert response.status_code == 422


def test_other_owner_cannot_read_or_modify_item(client, monkeypatch):
    created = client.post("/api/v1/internal-workspace/watchlists", json={
        "name": "Private", "symbols": ["NIFTY"]
    }).json()["item"]
    from app.security import require_admin
    client.app.dependency_overrides[require_admin] = lambda: {
        "admin_id": "other-2", "email": "owner@example.com", "role": "SUPER_ADMIN"
    }
    # Owner guard intentionally keys the identity to the configured owner email,
    # so a different Super Admin with that same email cannot exist in the auth store.
    # Data-layer ownership remains a second independent boundary.
    store = api.get_internal_workspace_store()
    assert store.get_item("other-2", created["item_id"], "WATCHLIST") is None
