from datetime import datetime, timedelta, timezone

from app.db import db
from app.security import hash_password


def seed_demo_data() -> None:
    try:
        if db.users.count_documents({}) == 0:
            users = [
                {
                    "email": "admin@retailflow.local",
                    "full_name": "System Administrator",
                    "password": hash_password("admin123"),
                    "role": "ADMIN",
                    "store_id": None,
                    "created_at": datetime.now(timezone.utc),
                },
                {
                    "email": "supply@retailflow.local",
                    "full_name": "Supply Chain Manager",
                    "password": hash_password("demo123"),
                    "role": "SUPPLY_CHAIN_MANAGER",
                    "store_id": None,
                    "created_at": datetime.now(timezone.utc),
                },
                {
                    "email": "store@retailflow.local",
                    "full_name": "Store Manager",
                    "password": hash_password("demo123"),
                    "role": "STORE_MANAGER",
                    "store_id": "store-14",
                    "created_at": datetime.now(timezone.utc),
                },
                {
                    "email": "customer@retailflow.local",
                    "full_name": "Customer",
                    "password": hash_password("demo123"),
                    "role": "CUSTOMER",
                    "store_id": None,
                    "created_at": datetime.now(timezone.utc),
                },
            ]
            db.users.insert_many(users)

        if db.products.count_documents({}) == 0:
            products = [
                {"product_id": "P-1001", "sku": "DRILL-104", "name": "Cordless Drill 18V", "category": "tools", "price": 149.99, "supplier_ids": ["SUP-01"], "dimensions": {"length": 30, "width": 18, "height": 22}, "weight_kg": 2.8, "metadata": {"brand": "TerraForge"}},
                {"product_id": "P-1002", "sku": "SAW-205", "name": "Circular Saw", "category": "tools", "price": 219.99, "supplier_ids": ["SUP-02"], "dimensions": {"length": 40, "width": 26, "height": 21}, "weight_kg": 4.5, "metadata": {"brand": "TerraForge"}},
                {"product_id": "P-1003", "sku": "LAMP-310", "name": "LED Work Light", "category": "lighting", "price": 79.99, "supplier_ids": ["SUP-03"], "dimensions": {"length": 15, "width": 10, "height": 11}, "weight_kg": 1.3, "metadata": {"brand": "PeakLine"}},
                {"product_id": "P-1004", "sku": "BAT-412", "name": "Battery Pack 5Ah", "category": "power-tools", "price": 109.99, "supplier_ids": ["SUP-04"], "dimensions": {"length": 12, "width": 8, "height": 6}, "weight_kg": 0.9, "metadata": {"brand": "VoltCore"}},
                {"product_id": "P-1005", "sku": "SCREW-881", "name": "Deck Screws Pack", "category": "fasteners", "price": 19.99, "supplier_ids": ["SUP-05"], "dimensions": {"length": 4, "width": 4, "height": 10}, "weight_kg": 0.4, "metadata": {"brand": "BuildRite"}},
            ]
            db.products.insert_many(products)

        if db.stores.count_documents({}) == 0:
            stores = [
                {"store_id": "store-01", "name": "Northside Home Center", "city": "Seattle", "state": "WA", "region": "Northwest", "lat": 47.6062, "lng": -122.3321, "manager_email": "store@retailflow.local"},
                {"store_id": "store-14", "name": "Downtown Pro Shop", "city": "Denver", "state": "CO", "region": "Mountain", "lat": 39.7392, "lng": -104.9903, "manager_email": "store@retailflow.local"},
            ]
            db.stores.insert_many(stores)

        if db.inventory.count_documents({}) == 0:
            inventory_docs = [
                {"store_id": "store-01", "product_id": "P-1001", "on_hand": 18, "reserved": 4, "incoming": 8, "safety_stock": 6, "reorder_point": 8, "updated_at": datetime.now(timezone.utc)},
                {"store_id": "store-14", "product_id": "P-1001", "on_hand": 7, "reserved": 3, "incoming": 2, "safety_stock": 6, "reorder_point": 8, "updated_at": datetime.now(timezone.utc)},
                {"store_id": "store-01", "product_id": "P-1002", "on_hand": 24, "reserved": 6, "incoming": 5, "safety_stock": 8, "reorder_point": 12, "updated_at": datetime.now(timezone.utc)},
                {"store_id": "store-14", "product_id": "P-1002", "on_hand": 11, "reserved": 2, "incoming": 1, "safety_stock": 8, "reorder_point": 12, "updated_at": datetime.now(timezone.utc)},
                {"store_id": "store-01", "product_id": "P-1003", "on_hand": 35, "reserved": 7, "incoming": 10, "safety_stock": 12, "reorder_point": 14, "updated_at": datetime.now(timezone.utc)},
                {"store_id": "store-14", "product_id": "P-1003", "on_hand": 18, "reserved": 3, "incoming": 6, "safety_stock": 12, "reorder_point": 14, "updated_at": datetime.now(timezone.utc)},
            ]
            db.inventory.insert_many(inventory_docs)

        if db.orders.count_documents({}) == 0:
            orders = [
                {"order_id": "ORD-1001", "customer_id": "CUST-001", "items": [{"product_id": "P-1001", "quantity": 2}], "delivery_address": {"city": "Denver", "state": "CO"}, "status": "fulfilled", "fulfillment_location": "warehouse-01", "payment_status": "paid", "created_at": datetime.now(timezone.utc) - timedelta(days=1), "delivery_details": {"eta_minutes": 120}},
                {"order_id": "ORD-1002", "customer_id": "CUST-002", "items": [{"product_id": "P-1002", "quantity": 1}], "delivery_address": {"city": "Seattle", "state": "WA"}, "status": "in_transit", "fulfillment_location": "warehouse-02", "payment_status": "paid", "created_at": datetime.now(timezone.utc), "delivery_details": {"eta_minutes": 180}},
            ]
            db.orders.insert_many(orders)

        if db.alerts.count_documents({}) == 0:
            alerts = [
                {"alert_id": "ALT-001", "title": "Low inventory at Store 14", "severity": "WARNING", "message": "Drill inventory is below reorder point.", "store_id": "store-14", "product_id": "P-1001", "acknowledged": False, "created_at": datetime.now(timezone.utc)},
                {"alert_id": "ALT-002", "title": "Delivery route delay", "severity": "CRITICAL", "message": "Route R-204 is running 34 minutes behind schedule.", "store_id": "store-14", "product_id": "P-1002", "acknowledged": False, "created_at": datetime.now(timezone.utc)},
            ]
            db.alerts.insert_many(alerts)

        if db.deliveries.count_documents({}) == 0:
            deliveries = [
                {"delivery_id": "DEL-001", "order_id": "ORD-1001", "vehicle_id": "veh-10", "route_id": "R-204", "status": "delayed", "eta_minutes": 160, "distance_km": 24.6, "progress": 0.7},
                {"delivery_id": "DEL-002", "order_id": "ORD-1002", "vehicle_id": "veh-11", "route_id": "R-110", "status": "on_time", "eta_minutes": 90, "distance_km": 16.8, "progress": 0.6},
            ]
            db.deliveries.insert_many(deliveries)
        if db.vehicles.count_documents({}) == 0:
            db.vehicles.insert_many(
                [
                    {"vehicle_id": "veh-10", "driver_id": "DRV-10", "status": "AVAILABLE", "capacity_kg": 350, "location": {"lat": 47.6062, "lng": -122.3321}},
                    {"vehicle_id": "veh-11", "driver_id": "DRV-11", "status": "AVAILABLE", "capacity_kg": 500, "location": {"lat": 39.7392, "lng": -104.9903}},
                ]
            )
        if db.drivers.count_documents({}) == 0:
            db.drivers.insert_many(
                [
                    {"driver_id": "DRV-10", "name": "Jordan Lee", "status": "AVAILABLE"},
                    {"driver_id": "DRV-11", "name": "Sam Rivera", "status": "AVAILABLE"},
                ]
            )
        if db.sales.count_documents({}) == 0:
            base_sales = {"P-1001": 4, "P-1002": 2, "P-1003": 6}
            sales = []
            for product_id, base_quantity in base_sales.items():
                for store_id in ("store-01", "store-14"):
                    for offset in range(1, 29):
                        sales.append(
                            {
                                "product_id": product_id,
                                "store_id": store_id,
                                "date": datetime.now(timezone.utc) - timedelta(days=offset),
                                "quantity": max(0, base_quantity + (offset % 5) - 2),
                            }
                        )
            db.sales.insert_many(sales)
    except Exception as exc:
        raise RuntimeError("Failed to seed RetailFlow demo data") from exc
