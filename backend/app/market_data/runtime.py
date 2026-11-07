"""Shared AIR market-data runtime singletons used by API and strategy engines."""
from app.market_data.hub import MarketDataHub
from app.market_data.router import MarketDataRouter
from app.market_data.provider_registry import MarketDataSourceRegistry
from app.market_data.instrument_registry import MarketInstrumentDirectory
from app.market_data.service import MarketDataService, set_default_market_data_service

market_data_router = MarketDataRouter()
market_data_hub = MarketDataHub()
market_data_sources = MarketDataSourceRegistry()
market_data_instruments = MarketInstrumentDirectory()
market_data_service = MarketDataService(market_data_router, market_data_hub, market_data_instruments)

set_default_market_data_service(market_data_service)
