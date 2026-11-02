# PulseNotify: Production-Grade Flight Price Monitoring Backend

PulseNotify is a distributed flight price monitoring backend service built with Python, Django REST Framework, Celery, Redis, and PostgreSQL. It automatically tracks flight price fluctuations and fires alerts when market prices hit or drop below user-defined thresholds.

---

## 🏛️ Architecture & System Design

```
   [ Client / Mobile / Web ]
               │
               ▼  (HTTP / JWT Auth)
  ┌──────────────────────────────────────────────────────────┐
  │                 Django REST Framework API                │
  │  • Auth (/api/auth/register/, /api/auth/login/)          │
  │  • Alerts (/api/alerts/)                                 │
  │  • Internal Mock Price Feed (/api/flights/price/)        │
  │  • Admin Analytics (/api/admin/summary/)                 │
  └────────────┬─────────────────────────────┬───────────────┘
               │                             │
    ORM Reads / Writes             HTTP requests.get()
               ▼                             ▼
       ┌───────────────┐          ┌──────────────────────┐
       │  PostgreSQL   │          │ Internal Price Feed  │
       └───────▲───────┘          └──────────────────────┘
               │                             ▲
      Logs & State Updates                   │ Fetch prices
               │                             │
  ┌────────────┴─────────────────────────────┴───────────────┐
  │              Celery Distributed Task Pipeline             │
  │                                                          │
  │  [ Celery Beat Scheduler ] ──(Every 60s)──► check_prices │
  │                                                  │       │
  │                                           .delay()       │
  │                                                  ▼       │
  │  [ Redis Broker ] ──────────────────► send_notification │
  │                                       (Worker executes)  │
  └──────────────────────────────────────────────────────────┘
```

---

## 🚀 Key Features & Highlights

1. **Decoupled Asynchronous Tasks (Celery + Redis)**:
   - Price checks occur automatically every 60 seconds via `Celery Beat`.
   - Alert notifications are dispatched asynchronously with `send_notification.delay()` so the scheduler and API calls are never blocked.
   - Idempotency guards prevent duplicate notification storms.
2. **Stateless JWT Authentication (`SimpleJWT`)**:
   - Short-lived Access Tokens & Refresh Tokens.
   - Auto-creates a `UserProfile` with role `user` using a Django `post_save` signal.
3. **Multi-Tenant Scoping & Security**:
   - Alerts are strictly scoped to the authenticated user (`get_queryset()` and IDOR defense).
   - Deleting an alert performs a **soft-delete** (`status = 'inactive'`) to stop background processing while preserving audit trails.
4. **Internal Micro-Feed Simulation**:
   - `GET /api/flights/price/?route=...` provides simulated real-time market prices, practicing robust backend-to-backend HTTP communication using `requests`.
5. **High-Performance Admin Analytics**:
   - `GET /api/admin/summary/` uses database-level SQL aggregations (`PriceAlert.objects.aggregate()`, `Count`, `Q`) and grouped annotations (`values().annotate()`). Zero Python loops for counting.
   - Protected by custom `IsAdminUser` permission (returns `403 Forbidden` to non-admin users).

---

## 📂 Project Structure

```
python-assignment/
├── manage.py
├── requirements.txt
├── docker-compose.yml
├── .env.example
├── .gitignore
├── pulse_notify_postman_collection.json
├── pulsenotify/
│   ├── __init__.py           # Exposes celery_app
│   ├── celery.py             # Celery application configuration
│   ├── urls.py               # Root URL configuration
│   ├── wsgi.py
│   ├── asgi.py
│   └── settings/
│       ├── __init__.py
│       ├── base.py           # Base configuration (JWT, Celery, Apps)
│       ├── local.py          # Local development overrides & DB fallback
│       └── production.py     # Hardened production settings
└── pulse/
    ├── __init__.py
    ├── apps.py               # Registers post_save signal on boot
    ├── models.py             # UserProfile, PriceAlert, NotificationLog
    ├── signals.py            # Auto-creates UserProfile on user registration
    ├── permissions.py        # IsAdminUser permission class
    ├── serializers.py        # DRF serializers
    ├── views.py              # API views
    ├── urls.py               # Route endpoints
    ├── tasks.py              # check_prices & send_notification Celery tasks
    └── tests.py              # Unit & integration test suites
```

---

## ⚙️ Quick Start & Installation

### 1. Prerequisites
- Python 3.10+
- Docker & Docker Compose (optional, for running Redis and PostgreSQL)

### 2. Setup Virtual Environment & Dependencies
```bash
# Clone or navigate to the repository
cd python-assignment

# Create and activate virtual environment
python -m venv .venv

# On Windows:
.\.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Spin Up PostgreSQL and Redis (Docker Compose)
```bash
docker compose up -d
```
*(Note: If Docker is not available, the local settings automatically fall back to SQLite for local development and testing).*

### 4. Run Migrations
```bash
python manage.py makemigrations pulse
python manage.py migrate
```

---

## 🏃 Running PulseNotify (3 Simultaneous Processes)

To run the complete distributed system in development:

### Terminal 1: Django API Server
```bash
python manage.py runserver 127.0.0.1:8000
```

### Terminal 2: Celery Worker
```bash
celery -A pulsenotify worker --loglevel=info
```
*(Windows tip: if running Celery on Windows natively, use `celery -A pulsenotify worker --loglevel=info -P solo`)*.

### Terminal 3: Celery Beat Scheduler
```bash
celery -A pulsenotify beat --loglevel=info
```

---

## 🧪 Running Automated Unit Tests

Run the complete test suite:
```bash
python manage.py test pulse
```
Output:
```
Found 21 test(s).
System check identified no issues (0 silenced).
.....................
----------------------------------------------------------------------
Ran 21 tests in 8.375s

OK
```

### Test Coverage includes:
- **PriceThresholdTest**: Boundary condition testing (`price < threshold`, `price > threshold`, `price == threshold`).
- **NotificationLogTest**: Verifies foreign key associations, message string accuracy, and database persistence.
- **AlertScopingTest**: Validates user tenant isolation (User 1 can never access or list User 2's alerts).
- **AuthEndpointsTest**: Tests registration, JWT token generation, role assignment, and login failures.
- **AlertAPITest**: Full CRUD lifecycle, input validation, soft-delete to `inactive`, and IDOR prevention.
- **FlightPriceAPITest**: Valid and invalid route requests on mock price feed.
- **AdminSummaryAPITest**: Admin authorization (200) vs regular user rejection (403), plus aggregate calculations.
- **CeleryTasksTest**: Mocked execution of `check_prices` and `send_notification`.

---

## 📡 API Reference

### 1. Authentication
* `POST /api/auth/register/` (Public)
  - Body: `{"username": "alice", "password": "securepass", "email": "alice@example.com"}`
  - Response (201): `{"username": "alice", "access": "eyJ...", "role": "user"}`
* `POST /api/auth/login/` (Public)
  - Body: `{"username": "alice", "password": "securepass"}`
  - Response (200): `{"access": "eyJ...", "refresh": "eyJ...", "username": "alice", "role": "user"}`

### 2. Price Alerts
* `POST /api/alerts/` (Protected - JWT)
  - Header: `Authorization: Bearer <token>`
  - Body: `{"origin": "DEL", "destination": "BOM", "threshold_price": "4500.00"}`
  - Response (201): `{"id": 1, "origin": "DEL", "destination": "BOM", "threshold_price": "4500.00", "status": "active", "created_at": "..."}`
* `GET /api/alerts/` (Protected - JWT)
  - Header: `Authorization: Bearer <token>`
  - Response (200): Returns alerts belonging only to the caller.
* `DELETE /api/alerts/<id>/` (Protected - JWT)
  - Header: `Authorization: Bearer <token>`
  - Response (200): `{"status": "inactive"}` (Soft delete). Returns 404 if not found or owned by another user.

### 3. Flight Price Feed (Internal)
* `GET /api/flights/price/?route=DEL-BOM` (Public / Internal)
  - Response (200): `{"route": "DEL-BOM", "price": 4200}`
  - Response (404): `{"error": "Route not found"}`

### 4. Admin Analytics
* `GET /api/admin/summary/` (Protected - Admin JWT)
  - Header: `Authorization: Bearer <admin_token>`
  - Response (200):
    ```json
    {
      "total_alerts": 24,
      "active_alerts": 18,
      "triggered_alerts": 4,
      "total_notifications": 11,
      "top_routes": [
        { "route": "DEL-BOM", "alert_count": 8 },
        { "route": "BLR-HYD", "alert_count": 6 }
      ]
    }
    ```
  - Response (403): If requested by a non-admin user.

---

## 📮 Postman Collection
A complete executable collection is included in [`pulse_notify_postman_collection.json`](file:///c:/Users/yoges/python-assignment/pulse_notify_postman_collection.json) covering all 13 test scenarios. Import it into Postman and run the collection runner.

