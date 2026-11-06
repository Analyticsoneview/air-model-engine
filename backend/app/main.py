from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from app.market_data.hub import MarketDataHub
from app.market_data.router import MarketDataRouter

app = FastAPI(title="AIR Market Data Gateway", version="0.2.0",
              description="Self-hosted single-Main-Account historical and live market-data gateway.")
market_data_router = MarketDataRouter()
market_data_hub = MarketDataHub()


class MainAccountSelection(BaseModel):
    provider: str
    account_id: str


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "air-market-data-gateway"}


@app.get("/api/v1/market-data/status")
async def market_data_status() -> dict:
    return {
        "routing": market_data_router.status(),
        "stream": market_data_hub.status(),
        "note": "No broker provider is connected until a provider adapter and credentials are configured.",
    }


@app.put("/api/v1/market-data/main-account")
async def select_main_account(selection: MainAccountSelection) -> dict:
    try:
        await market_data_router.set_main_account(selection.provider, selection.account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"routing": market_data_router.status()}


@app.delete("/api/v1/market-data/main-account")
async def disconnect_main_account() -> dict:
    try:
        await market_data_router.clear_main_account()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"routing": market_data_router.status()}


@app.websocket("/ws/market-data")
async def market_data_stream(websocket: WebSocket) -> None:
    await market_data_hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await market_data_hub.disconnect(websocket)
