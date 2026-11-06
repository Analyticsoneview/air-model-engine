from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from app.market_data.hub import MarketDataHub
from app.market_data.router import MarketDataRouter

app = FastAPI(title="AIR Market Data Gateway", version="0.1.0",
              description="Self-hosted multi-provider historical and WebSocket market-data gateway.")
market_data_router = MarketDataRouter()
market_data_hub = MarketDataHub()

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "air-market-data-gateway"}

@app.get("/api/v1/market-data/status")
async def market_data_status() -> dict:
    return {"routing": market_data_router.status(), "stream": market_data_hub.status(),
            "note": "No broker provider is connected until an adapter and credentials are configured."}

@app.websocket("/ws/market-data")
async def market_data_stream(websocket: WebSocket) -> None:
    await market_data_hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await market_data_hub.disconnect(websocket)
