from types import SimpleNamespace

import pytest

from app.security import hash_password, verify_password
from app.services.chatbot_service import answer_chat_question
from app.services.forecast_service import build_forecast, build_replenishment_recommendation


class FakeCollection:
    def __init__(self, items=None, count=0):
        self.items = items or []
        self.count_value = count

    async def count_documents(self, *args, **kwargs):
        return self.count_value

    def find(self, *args, **kwargs):
        return FakeCursor(self.items)

    async def find_one(self, *args, **kwargs):
        return self.items[0] if self.items else None


class FakeCursor:
    def __init__(self, items):
        self.items = items
        self.index = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.index >= len(self.items):
            raise StopIteration
        item = self.items[self.index]
        self.index += 1
        return item

    async def to_list(self, length=100):
        return self.items[:length]


@pytest.mark.asyncio
async def test_hashing_round_trip():
    password = 'admin123'
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True


def test_forecast_and_replenishment_logic():
    forecast = build_forecast('P-1001', 'store-14', history=[20, 22, 18, 24, 25, 19, 23])
    assert forecast['forecast_7d'] > 0
    assert forecast['forecast_30d'] > 0

    recommended = build_replenishment_recommendation(available=8, incoming=2, safety_stock=6, forecast_7d=21, reorder_point=10)
    assert recommended >= 0


@pytest.mark.asyncio
async def test_chatbot_question(monkeypatch):
    fake_inventory = [
        {'store_id': 'store-14', 'product_id': 'P-1001', 'on_hand': 5, 'reserved': 2, 'reorder_point': 8},
        {'store_id': 'store-01', 'product_id': 'P-1003', 'on_hand': 40, 'reserved': 2, 'reorder_point': 20},
    ]
    fake_orders = [{'order_id': 'ORD-1001', 'status': 'fulfilled'}]
    fake_deliveries = [{'delivery_id': 'DEL-001', 'status': 'delayed'}]
    fake_alerts = [{'alert_id': 'ALT-001', 'acknowledged': False}]
    fake_products = [{'product_id': 'P-1001', 'name': 'Cordless Drill 18V'}]

    import app.services.chatbot_service as chatbot_service

    monkeypatch.setattr(chatbot_service, 'db', SimpleNamespace(
        inventory=FakeCollection(fake_inventory),
        orders=FakeCollection(fake_orders, count=1),
        deliveries=FakeCollection(fake_deliveries, count=1),
        alerts=FakeCollection(fake_alerts, count=1),
        products=FakeCollection(fake_products),
    ))

    response = await answer_chat_question('Which stores are at risk of stockout?', 'SUPPLY_CHAIN_MANAGER')
    assert 'risk' in response['answer'].lower() or 'stockout' in response['answer'].lower()
    assert 'items' in response
