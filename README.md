# RetailFlow — Intelligent Retail Supply Chain & Fulfillment Platform

RetailFlow is a production-style retail supply-chain control tower built with FastAPI, MongoDB, Redis, Celery, Kafka, React, and Docker Compose. The project is designed as a concrete portfolio system for supply-chain and operations engineering roles, with realistic synthetic data and a dashboard-first workflow.

## Overview

The platform simulates an omnichannel retailer that manages stores, warehouses, products, suppliers, fulfillment, route planning, delivery tracking, demand forecasting, replenishment, and operational alerts. It includes:

- FastAPI backend with RBAC and JWT auth
- MongoDB-backed document models for inventory, orders, deliveries, alerts, and analytics
- Redis caching for dashboard queries and session state
- Celery workers for async task processing
- Kafka event processing for order and delivery events
- Warehouse dashboards, fulfillment-decision history, and cross-warehouse performance comparison
- React + Vite + Tailwind frontend dashboard
- OpenAI-compatible Copilot with role-scoped read tools and explicit confirmation before supported write actions
- end-to-end test suite with pytest
- Docker Compose setup for local orchestration

## Architecture

- Backend: Python 3.12, FastAPI, Pydantic v2, Motor, Redis, Celery, Kafka
- Frontend: React, TypeScript, Vite, Tailwind, Recharts
- Data: MongoDB with aggregation-heavy analytics
- Ops: Docker Compose, Nginx, Prometheus, Grafana

## Quick start

1. Copy `.env.example` to `.env`.
2. Replace `SECRET_KEY` and `GRAFANA_ADMIN_PASSWORD` with unique values before startup. Set `OPENAI_API_KEY` to enable the Copilot; the rest of the application works without it.
3. Start the full stack:

```bash
docker compose up --build
```

3. Open the frontend at http://localhost:5173
4. Login with demo credentials:
   - admin / admin123
   - supply_chain_manager / demo123
   - store_manager / demo123
   - customer / demo123

## Local backend development

```bash
cd backend
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Frontend development

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

## Testing

```bash
cd backend
pytest
```

## Key features

- Inventory reservation with atomic updates
- Demand forecasting with moving average and exponential smoothing
- Replenishment recommendations based on demand and lead time
- Delivery ETA estimation with simple interpretable model
- Alert generation and acknowledgment
- Role-based Copilot access, conversation history, structured page context, and confirmation-gated actions
- Analytics dashboard backed by Mongo aggregation
- Synthetic seed data for stores, products, fulfillment centers, routes and deliveries

## Notes

Domain changes are first written to a MongoDB outbox and a separate `kafka-worker` publishes and consumes them. Failed publishes are retried, and consumers deduplicate by event ID, but MongoDB and Kafka do not share a transaction; this is not an exactly-once or guaranteed-delivery system. The single-broker Compose configuration is for local development, not highly available production use.

The frontend uses React Router 7 and requires Node.js 20 or later. The live tracking page displays periodically refreshed delivery coordinates and status; it does not provide a geographic basemap. Set a valid OpenAI-compatible provider and API key to get model-backed Copilot responses; without a key the Copilot reports that it is not configured.

This project uses realistic synthetic data for demonstration purposes only. It is not tied to any proprietary retailer brand or live production system.
