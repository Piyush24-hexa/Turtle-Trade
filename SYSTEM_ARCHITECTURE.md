# Turtle Trade Intelligence Platform - System Architecture

This document describes the high-level architecture of the refactored Turtle Trade Intelligence Platform.
The application operates as an autonomous, multi-layered trading research and execution framework. 

## Architectural Overview

The platform uses a decoupled design separating ingestion, analysis, market condition evaluation, signal generation, formatting, and execution.

### Components by Functionality

#### 1. Entrypoint (`main.py`)
Acts as the central execution orchestrator. It manages the runtime clock, global states, and module loading. It invokes specific **Scanners** depending on the time of day and market conditions without tightly coupling scanning logic to the runtime loop.

#### 2. Scanners (`scanners/`)
Scanning pipelines orchestrate the heavy lifting of evaluating a list of assets.
- `equity_scanner.py`: Triggers core ML/Technical scanning on NSE standard hours.
- `options_scanner.py`: Targets specific FNO behaviors for the broad market indexes.
- `crypto_scanner.py`: A 24/7 scanning cycle utilizing global feeds to track top-cap altcoins.

#### 3. Core Engine (`signal_generator.py`)
Provides the core decision logic. Synthesizes inputs into raw, unformatted dictionaries containing confidence-scoring and signal conviction grading.

#### 4. Intelligence & Analysis (`analysis/` & `signals/`)
- ML Models: Random Forests and LSTMs for probability scoring.
- Fundamentals: Real-time company fundamental metrics.
- Pattern Recognition: Candlestick and chart pattern detection models.
- Sentiment & News: FinBERT analyzing sentiment polarity of live aggregated news feeds.

#### 5. Data & Execution (`data_collector.py` & `execution/`)
- `data_collector.py`: Responsible solely for fetching market data and persisting OHLCV data. 
- `execution/order_manager.py`: Centralized source of truth for handling trade lifecycle states, position limits, unrealized/realized P&L, and all database interactions relating to user positions.
- `execution/signal_formatter.py`: Generates the richly-styled HTML messages used for alerts and telegram tracking based on the completed raw signals.

#### 6. Visualization & UI (`api_server.py` & `dashboard/`)
- Provides REST API endpoints (abstracted via `demo_data.py` fallback routes) that serve live dashboard analytics.
- Integrated LLM agent routes handling real-time AI context evaluation on specific markets or signal items.

## Database Design

The application utilizes an SQLite single-file structure (`trading_bot.db`) cleanly separated into logical layers:
- **`ohlcv`**: Handled via `data_collector`. Raw market tick and candlestick data.
- **`orders`**: Handled via `order_manager`. Current and Historical trades.
- **`order_events` & `news_signals`**: Detailed logging tables managed by order manager.

## Key Improvements
- Unified all signal formatting into the formatter module for consistent cross-market messaging.
- Refactored monolith methods into decoupled domain scanners (`equity`, `options`, `crypto`).
- Stripped overlapping/legacy database implementations in favor of the optimized execution layer structure.
- Removed legacy test stubs and simplified the `main.py` control loop.
