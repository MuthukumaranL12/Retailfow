from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services import chatbot_service


class Cursor:
    def __init__(self, items):
        self.items = list(items)

    def limit(self, count):
        self.items = self.items[:count]
        return self

    def sort(self, *_args):
        return self

    def __iter__(self):
        return iter(self.items)


class Collection:
    def __init__(self, items=()):
        self.items = list(items)
        self.queries = []

    def find(self, query=None, _projection=None):
        query = query or {}
        self.queries.append(query)
        matched = []
        for item in self.items:
            if all(
                (key not in item if value == {"$ne": True} else item.get(key) == value)
                if not isinstance(value, dict) or "$in" not in value
                else item.get(key) in value["$in"]
                for key, value in query.items()
            ):
                matched.append(item)
        return Cursor(matched)

    def insert_one(self, document):
        self.items.append(deepcopy(document))
        return SimpleNamespace(inserted_id="new-id")

    def find_one(self, query=None, _projection=None):
        query = query or {}
        self.queries.append(query)
        return next((item for item in self.items if all(item.get(k) == v for k, v in query.items())), None)

    def count_documents(self, _query):
        return 0

    def update_one(self, query, update):
        for document in self.items:
            if all(document.get(key) == value for key, value in query.items() if key != "pending_actions"):
                if "$push" in update:
                    field, value = next(iter(update["$push"].items()))
                    document.setdefault(field, []).extend(value["$each"])
                    if "$slice" in value:
                        document[field] = document[field][value["$slice"] :]
                    return SimpleNamespace(matched_count=1)
                elem = query.get("pending_actions", {}).get("$elemMatch", {})
                action = next(
                    (
                        item
                        for item in document.get("pending_actions", [])
                        if all(item.get(k) == v for k, v in elem.items())
                    ),
                    None,
                )
                if action:
                    for path, value in update.get("$set", {}).items():
                        field = path.split(".$.", 1)[1]
                        action[field] = value
                    return SimpleNamespace(matched_count=1)
                if not elem:
                    for field, value in update.get("$set", {}).items():
                        document[field] = value
                    if "$set" in update:
                        return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)

    def delete_one(self, query):
        for index, document in enumerate(self.items):
            if all(document.get(key) == value for key, value in query.items()):
                del self.items[index]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


@pytest.mark.asyncio
async def test_mocked_llm_gets_real_scoped_tool_data(monkeypatch):
    inventory = Collection(
        [
            {"store_id": "store-14", "product_id": "P-1001", "on_hand": 4, "reserved": 1, "reorder_point": 5},
            {"store_id": "store-15", "product_id": "P-2000", "on_hand": 100, "reserved": 0, "reorder_point": 10},
        ]
    )
    monkeypatch.setattr(
        chatbot_service,
        "db",
        SimpleNamespace(inventory=inventory),
    )
    monkeypatch.setattr(chatbot_service.settings, "openai_api_key", "test-key")
    seen = []

    async def mock_completion(messages, tools):
        seen.append((messages, tools))
        if len(seen) == 1:
            return {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "function": {"name": "get_inventory_risks", "arguments": "{}"},
                    }
                ],
            }
        return {"content": "P-1001 at store-14 is at risk.", "tool_calls": []}

    monkeypatch.setattr(chatbot_service, "_request_completion", mock_completion)
    result = await chatbot_service.answer_chat_question(
        "Which item is at risk?",
        {"role": "STORE_MANAGER", "store_id": "store-14", "email": "manager@example.com"},
        conversation_id="conversation-1",
    )

    assert result["answer"] == "P-1001 at store-14 is at risk."
    assert result["items"][0]["result"]["items"] == [
        {"store_id": "store-14", "product_id": "P-1001", "available": 3, "reorder_point": 5}
    ]
    assert inventory.queries[0] == {"store_id": "store-14"}
    assert "P-1001" in seen[1][0][-1]["content"]


@pytest.mark.asyncio
async def test_openai_compatible_completion_uses_configured_provider(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ready"}}]}

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, headers, json):
            captured.update(url=url, headers=headers, payload=json)
            return FakeResponse()

    monkeypatch.setattr(chatbot_service.settings, "llm_provider", "https://llm.example/v1")
    monkeypatch.setattr(chatbot_service.settings, "llm_model", "retail-model")
    monkeypatch.setattr(chatbot_service.settings, "openai_api_key", "secret-test-key")
    monkeypatch.setattr(chatbot_service.httpx, "AsyncClient", FakeClient)

    result = await chatbot_service._request_completion([{"role": "user", "content": "hello"}], [])

    assert result == {"content": "ready"}
    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-test-key"
    assert captured["payload"]["model"] == "retail-model"


@pytest.mark.asyncio
async def test_missing_api_key_returns_explicit_not_configured_response(monkeypatch):
    monkeypatch.setattr(chatbot_service.settings, "openai_api_key", "")

    async def must_not_call_llm(*_args, **_kwargs):
        raise AssertionError("LLM should not be called without a key")

    monkeypatch.setattr(chatbot_service, "_request_completion", must_not_call_llm)
    response = await chatbot_service.answer_chat_question("How is stock?")

    assert response["status"] == "not_configured"
    assert "OPENAI_API_KEY is not set" in response["answer"]


def test_customer_cannot_call_inventory_tool(monkeypatch):
    inventory = Collection([{"store_id": "store-14", "product_id": "P-1001"}])
    monkeypatch.setattr(chatbot_service, "db", SimpleNamespace(inventory=inventory))

    with pytest.raises(chatbot_service.ChatbotError, match="permission"):
        chatbot_service.execute_tool("get_inventory_risks", {}, {"role": "CUSTOMER", "email": "buyer@example.com"})
    assert inventory.queries == []


def test_requested_tool_registry_is_model_visible_and_allowlisted():
    names = {tool["function"]["name"] for tool in chatbot_service.TOOL_SPECS}
    expected = {
        "get_inventory_status",
        "get_low_stock_products",
        "get_stockout_risks",
        "get_order_details",
        "get_delayed_deliveries",
        "get_delivery_details",
        "get_vehicle_status",
        "get_store_performance",
        "get_warehouse_performance",
        "get_demand_forecast",
        "get_replenishment_recommendations",
        "get_route_information",
        "get_supply_chain_kpis",
        "get_alerts",
        "get_daily_summary",
        "get_fulfillment_decision",
        "stage_inventory_restock",
        "stage_replenishment_approval",
    }

    assert names == expected
    assert {
        tool["function"]["name"]
        for tool in chatbot_service._model_tools_for_role(
            {"role": "ADMIN", "email": "admin@example.com"}
        )
    } == expected
    assert all(
        tool["function"]["parameters"]["additionalProperties"] is False
        for tool in chatbot_service.TOOL_SPECS
    )


def test_store_performance_and_inventory_are_real_and_store_scoped(monkeypatch):
    stores = Collection(
        [
            {"store_id": "store-14", "name": "Downtown Pro Shop"},
            {"store_id": "store-15", "name": "Other Shop"},
        ]
    )
    inventory = Collection(
        [
            {"store_id": "store-14", "product_id": "P-1001", "on_hand": 7, "reserved": 3, "reorder_point": 5},
            {"store_id": "store-15", "product_id": "P-2000", "on_hand": 2, "reserved": 0, "reorder_point": 4},
        ]
    )
    products = Collection(
        [{"product_id": "P-1001", "name": "Cordless Drill 18V"}, {"product_id": "P-2000", "name": "Saw"}]
    )
    orders = Collection(
        [{"order_id": "ORD-1001", "fulfillment_location": "store-14", "status": "FULFILLED"}]
    )
    deliveries = Collection(
        [{"delivery_id": "DEL-001", "fulfillment_location": "store-14", "status": "COMPLETED"}]
    )
    monkeypatch.setattr(
        chatbot_service,
        "db",
        SimpleNamespace(stores=stores, inventory=inventory, products=products, orders=orders, deliveries=deliveries),
    )
    user = {"role": "STORE_MANAGER", "store_id": "store-14", "email": "manager@example.com"}

    inventory_result = chatbot_service.execute_tool("get_inventory_status", {}, user)
    performance = chatbot_service.execute_tool("get_store_performance", {}, user)

    assert inventory_result["items"] == [
        {
            "store_id": "store-14",
            "product_id": "P-1001",
            "on_hand": 7,
            "reserved": 3,
            "reorder_point": 5,
            "product_name": "Cordless Drill 18V",
            "available": 4.0,
        }
    ]
    assert performance["items"][0]["summary"]["fulfilled_orders"] == 1
    assert performance["items"][0]["summary"]["available_units"] == 4
    assert inventory.queries[0] == {"store_id": "store-14"}
    assert stores.queries[0] == {"store_id": "store-14"}

    with pytest.raises(chatbot_service.ChatbotError, match="not authorized"):
        chatbot_service.execute_tool("get_store_performance", {"store_id": "store-15"}, user)


def test_warehouse_performance_uses_existing_service_and_assigned_scope(monkeypatch):
    from app.services import warehouse_service

    calls = []
    monkeypatch.setattr(
        warehouse_service,
        "get_warehouse_dashboard",
        lambda warehouse_id, include_records: calls.append((warehouse_id, include_records))
        or {"warehouse": {"warehouse_id": warehouse_id}, "summary": {"orders": {"total": 3}}},
    )
    user = {
        "role": "WAREHOUSE_MANAGER",
        "warehouse_id": "WH-14",
        "email": "manager@example.com",
    }

    result = chatbot_service.execute_tool(
        "get_warehouse_performance", {"warehouse_id": "WH-14"}, user
    )
    assert result["summary"]["orders"]["total"] == 3
    assert calls == [("WH-14", False)]
    with pytest.raises(chatbot_service.ChatbotError, match="not authorized"):
        chatbot_service.execute_tool(
            "get_warehouse_performance", {"warehouse_id": "WH-15"}, user
        )
    assert len(calls) == 1


def test_read_tool_scope_forbids_cross_store_delivery_data(monkeypatch):
    deliveries = Collection(
        [{"delivery_id": "DEL-001", "fulfillment_location": "store-15", "status": "DELAYED"}]
    )
    monkeypatch.setattr(chatbot_service, "db", SimpleNamespace(deliveries=deliveries))
    user = {"role": "STORE_MANAGER", "store_id": "store-14", "email": "manager@example.com"}

    result = chatbot_service.execute_tool("get_delayed_deliveries", {}, user)

    assert result == {"count": 0, "items": []}
    assert deliveries.queries[0] == {
        "status": {"$in": ["DELAYED", "delayed"]},
        "fulfillment_location": "store-14",
    }


def test_order_and_fulfillment_tools_only_return_customer_owned_records(monkeypatch):
    orders = Collection(
        [
            {
                "order_id": "ORD-1001",
                "customer_id": "buyer@example.com",
                "fulfillment_location": "store-14",
                "status": "ASSIGNED",
                "fulfillment_decision": {"selected_location": "store-14", "reasons": ["available stock"]},
            },
            {
                "order_id": "ORD-1002",
                "customer_id": "other@example.com",
                "fulfillment_location": "store-15",
                "status": "ASSIGNED",
            },
        ]
    )
    monkeypatch.setattr(chatbot_service, "db", SimpleNamespace(orders=orders))
    buyer = {"role": "CUSTOMER", "email": "buyer@example.com"}

    details = chatbot_service.execute_tool("get_order_details", {"order_id": "ORD-1001"}, buyer)
    decision = chatbot_service.execute_tool(
        "get_fulfillment_decision", {"order_id": "ORD-1001"}, buyer
    )
    hidden = chatbot_service.execute_tool("get_order_details", {"order_id": "ORD-1002"}, buyer)

    assert details["found"] is True
    assert details["order"]["customer_id"] == "buyer@example.com"
    assert decision["decision"]["selected_location"] == "store-14"
    assert hidden == {"found": False, "order": None}
    assert orders.queries[0] == {"order_id": "ORD-1001", "customer_id": "buyer@example.com"}
    assert orders.queries[2] == {"order_id": "ORD-1002", "customer_id": "buyer@example.com"}


def test_model_can_only_stage_restock_until_user_confirms(monkeypatch):
    conversation = {
        "conversation_id": "conversation-1",
        "owner_email": "warehouse@example.com",
        "pending_actions": [],
    }
    conversations = Collection([conversation])
    inventory = Collection([{"product_id": "P-1001", "store_id": "store-14", "on_hand": 2}])
    monkeypatch.setattr(
        chatbot_service,
        "db",
        SimpleNamespace(conversations=conversations, inventory=inventory),
    )
    restocks = []
    monkeypatch.setattr(
        chatbot_service,
        "restock_inventory",
        lambda *args: restocks.append(args) or {"type": "RESTOCK", "quantity": args[2]},
    )
    warehouse_user = {"role": "WAREHOUSE_MANAGER", "email": "warehouse@example.com"}
    staged = chatbot_service.execute_tool(
        "stage_inventory_restock",
        {"product_id": "P-1001", "store_id": "store-14", "quantity": 10},
        warehouse_user,
        "conversation-1",
    )

    assert staged["confirmation_required"] is True
    assert conversation["pending_actions"][0]["status"] == "PENDING_CONFIRMATION"
    assert restocks == []

    declined = chatbot_service.confirm_staged_action(
        "conversation-1", staged["action_id"], warehouse_user, confirmed=False
    )
    assert declined["status"] == "declined"
    assert conversation["pending_actions"][0]["status"] == "DECLINED"
    assert restocks == []

    staged_again = chatbot_service.execute_tool(
        "stage_inventory_restock",
        {"product_id": "P-1001", "store_id": "store-14", "quantity": 10},
        warehouse_user,
        "conversation-1",
    )
    confirmed = chatbot_service.confirm_staged_action(
        "conversation-1", staged_again["action_id"], warehouse_user, confirmed=True
    )
    assert confirmed["status"] == "confirmed"
    assert len(restocks) == 1
    assert restocks[0][:3] == ("P-1001", "store-14", 10)


def test_model_can_only_stage_replenishment_approval_until_user_confirms(monkeypatch):
    conversation = {
        "conversation_id": "conversation-approval",
        "owner_email": "manager@example.com",
        "pending_actions": [],
    }
    conversations = Collection([conversation])
    recommendations = Collection(
        [
            {
                "recommendation_id": "RR-store-14-P-1001",
                "status": "PENDING",
                "store_id": "store-14",
                "product_id": "P-1001",
                "recommended_qty": 18,
            }
        ]
    )
    monkeypatch.setattr(
        chatbot_service,
        "db",
        SimpleNamespace(conversations=conversations, replenishment_recommendations=recommendations),
    )
    approvals = []
    monkeypatch.setattr(
        chatbot_service,
        "approve_recommendation",
        lambda recommendation_id, user: approvals.append((recommendation_id, user["email"]))
        or {"recommendation_id": recommendation_id, "status": "APPROVED"},
    )
    manager = {"role": "STORE_MANAGER", "store_id": "store-14", "email": "manager@example.com"}

    staged = chatbot_service.execute_tool(
        "stage_replenishment_approval",
        {"recommendation_id": "RR-store-14-P-1001"},
        manager,
        "conversation-approval",
    )
    assert staged["confirmation_required"] is True
    assert staged["action"]["quantity"] == 18
    assert approvals == []

    declined = chatbot_service.confirm_staged_action(
        "conversation-approval", staged["action_id"], manager, confirmed=False
    )
    assert declined["status"] == "declined"
    assert approvals == []

    staged_again = chatbot_service.execute_tool(
        "stage_replenishment_approval",
        {"recommendation_id": "RR-store-14-P-1001"},
        manager,
        "conversation-approval",
    )
    confirmed = chatbot_service.confirm_staged_action(
        "conversation-approval", staged_again["action_id"], manager, confirmed=True
    )
    assert confirmed["status"] == "confirmed"
    assert confirmed["approval"]["status"] == "APPROVED"
    assert approvals == [("RR-store-14-P-1001", "manager@example.com")]


def test_replenishment_approval_staging_enforces_store_scope(monkeypatch):
    recommendations = Collection(
        [
            {
                "recommendation_id": "RR-store-15-P-1001",
                "status": "PENDING",
                "store_id": "store-15",
                "product_id": "P-1001",
                "recommended_qty": 12,
            }
        ]
    )
    conversations = Collection(
        [{"conversation_id": "conversation-approval", "owner_email": "manager@example.com"}]
    )
    monkeypatch.setattr(
        chatbot_service,
        "db",
        SimpleNamespace(conversations=conversations, replenishment_recommendations=recommendations),
    )
    with pytest.raises(chatbot_service.ChatbotError, match="authorized to change inventory"):
        chatbot_service.execute_tool(
            "stage_replenishment_approval",
            {"recommendation_id": "RR-store-15-P-1001"},
            {"role": "STORE_MANAGER", "store_id": "store-14", "email": "manager@example.com"},
            "conversation-approval",
        )


@pytest.mark.asyncio
async def test_conversation_crud_and_bounded_history(monkeypatch):
    from app.api.v1 import chatbot as chatbot_api

    conversations = Collection()
    monkeypatch.setattr(chatbot_api, "db", SimpleNamespace(conversations=conversations))
    user = {"email": "analyst@example.com", "role": "ANALYST"}
    created = await chatbot_api.create_conversation(user)
    stored = conversations.items[0]
    stored["messages"] = [
        {"question": f"question-{index}", "answer": f"answer-{index}"}
        for index in range(20)
    ]
    captured = {}

    async def mock_answer(question, current_user, page_context, history, conversation_id):
        captured.update(
            question=question,
            page_context=page_context,
            history=history,
            conversation_id=conversation_id,
        )
        return {"answer": "The report is ready.", "items": [], "status": "ok"}

    monkeypatch.setattr(chatbot_api, "answer_chat_question", mock_answer)
    response = await chatbot_api.query_chat(
        chatbot_api.ChatQuery(
            question="Summarize this page",
            page_context=chatbot_service.PageContext(page="/analytics"),
            conversation_id=created["conversation_id"],
        ),
        user,
    )

    assert response["conversation_id"] == created["conversation_id"]
    assert len(captured["history"]) == 24
    assert captured["history"][0] == {"role": "user", "content": "question-8"}
    assert captured["page_context"] == {"page": "/analytics"}
    history_response = await chatbot_api.get_conversation(created["conversation_id"], user)
    assert len(history_response["messages"]) == 21
    assert history_response["messages"][-1]["answer"] == "The report is ready."
    deleted = await chatbot_api.delete_conversation(created["conversation_id"], user)
    assert deleted["message"] == "Conversation deleted"
