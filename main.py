import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Dict, Any
import uuid

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document
from schemas import Userprofile, Checkin, Craving, Badge

app = FastAPI(title="Quit Smoking Gamified API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Helpers

def _collection(name: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database indisponível")
    return db[name]


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _as_utc_datetime(d: date) -> datetime:
    # Store dates as midnight UTC datetimes to be BSON-compatible
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _ensure_user(user_uid: str) -> Dict[str, Any]:
    doc = _collection("userprofile").find_one({"uid": user_uid})
    if not doc:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return doc


# Request models for endpoints
class CreateUserRequest(Userprofile):
    pass


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    quit_date: Optional[date] = None
    daily_cig_before: Optional[int] = None
    price_per_pack: Optional[float] = None
    cigs_per_pack: Optional[int] = None
    currency: Optional[str] = None


class CheckinRequest(BaseModel):
    user_id: str
    date: Optional[date] = None
    cigarettes_count: int = 0


class CravingRequest(BaseModel):
    user_id: str
    intensity: int
    trigger: Optional[str] = None
    note: Optional[str] = None
    occurred_at: Optional[datetime] = None


# Basic routes
@app.get("/")
def read_root():
    return {"message": "Quit Smoking Gamified API"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else None
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# Schema endpoint (optional viewer support)
@app.get("/schema")
def get_schema():
    return {
        "userprofile": Userprofile.model_json_schema(),
        "checkin": Checkin.model_json_schema(),
        "craving": Craving.model_json_schema(),
        "badge": Badge.model_json_schema(),
    }


# Users
@app.post("/api/users")
def create_user(payload: CreateUserRequest):
    uid = uuid.uuid4().hex
    data = payload.model_dump()
    data["uid"] = uid
    create_document("userprofile", data)
    return {"user_id": uid}


@app.get("/api/users/{user_id}")
def get_user(user_id: str):
    doc = _ensure_user(user_id)
    doc["id"] = doc.get("uid")
    # Remove internal _id for cleaner payload
    if "_id" in doc:
        doc.pop("_id")
    return doc


@app.put("/api/users/{user_id}")
def update_user(user_id: str, payload: UpdateUserRequest):
    update = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    if not update:
        return {"updated": False}
    res = _collection("userprofile").update_one({"uid": user_id}, {"$set": update, "$currentDate": {"updated_at": True}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return {"updated": True}


# Check-ins
@app.post("/api/checkins")
def upsert_checkin(payload: CheckinRequest):
    _ensure_user(payload.user_id)
    d = payload.date or _today_utc()
    ddt = _as_utc_datetime(d)
    # Enforce single check-in per day per user
    _collection("checkin").update_one(
        {"user_id": payload.user_id, "date": ddt},
        {"$set": {"cigarettes_count": payload.cigarettes_count, "date": ddt}, "$currentDate": {"updated_at": True}},
        upsert=True,
    )
    _maybe_award_badges(payload.user_id)
    return {"ok": True}


@app.get("/api/checkins")
def list_checkins(user_id: str = Query(...), limit: int = Query(30, ge=1, le=365)):
    _ensure_user(user_id)
    docs = (
        _collection("checkin")
        .find({"user_id": user_id})
        .sort("date", -1)
        .limit(limit)
    )
    items = []
    for d in docs:
        dt = d.get("date")
        if isinstance(dt, datetime):
            date_str = dt.date().isoformat()
        elif isinstance(dt, date):
            date_str = dt.isoformat()
        else:
            date_str = str(dt)
        items.append({
            "id": str(d.get("_id")),
            "date": date_str,
            "cigarettes_count": d.get("cigarettes_count", 0),
        })
    return {"items": items}


# Cravings
@app.post("/api/cravings")
def create_craving(payload: CravingRequest):
    _ensure_user(payload.user_id)
    data = payload.model_dump()
    if not data.get("occurred_at"):
        data["occurred_at"] = datetime.now(timezone.utc)
    create_document("craving", data)
    return {"ok": True}


# Badges
@app.get("/api/badges")
def list_badges(user_id: str = Query(...)):
    _ensure_user(user_id)
    docs = _collection("badge").find({"user_id": user_id}).sort("awarded_at", -1)
    items = []
    for b in docs:
        aw = b.get("awarded_at")
        if isinstance(aw, datetime):
            aw_str = aw.isoformat()
        else:
            aw_str = str(aw)
        items.append({
            "id": str(b.get("_id")),
            "key": b.get("key"),
            "name": b.get("name"),
            "description": b.get("description"),
            "icon": b.get("icon", "⭐"),
            "awarded_at": aw_str,
        })
    return {"items": items}


# Dashboard
@app.get("/api/dashboard")
def dashboard(user_id: str = Query(...)):
    user = _ensure_user(user_id)
    stats = _compute_stats(user)
    _maybe_award_badges(user_id, stats)
    badges = list(_collection("badge").find({"user_id": user_id}))
    badges_fmt = [{
        "key": b.get("key"),
        "name": b.get("name"),
        "description": b.get("description"),
        "icon": b.get("icon", "⭐"),
        "awarded_at": b.get("awarded_at").isoformat() if isinstance(b.get("awarded_at"), datetime) else str(b.get("awarded_at")),
    } for b in badges]
    return {"user": {"name": user.get("name"), "currency": user.get("currency", "$")}, "stats": stats, "badges": badges_fmt}


# Business logic

def _compute_stats(user_doc: Dict[str, Any]) -> Dict[str, Any]:
    quit_date = user_doc.get("quit_date")
    if isinstance(quit_date, datetime):
        quit_date = quit_date.date()
    today = _today_utc()
    days_since_quit = (today - quit_date).days if quit_date else 0

    baseline_daily = int(user_doc.get("daily_cig_before", 0) or 0)
    price_per_pack = float(user_doc.get("price_per_pack", 0) or 0.0)
    cigs_per_pack = int(user_doc.get("cigs_per_pack", 20) or 20)
    currency = user_doc.get("currency", "$")

    # Fetch checkins since quit
    checkins = list(_collection("checkin").find({"user_id": user_doc.get("uid")})) if quit_date else []
    days_logged: Dict[date, int] = {}
    for c in checkins:
        dt = c.get("date")
        if isinstance(dt, datetime):
            d = dt.date()
        elif isinstance(dt, date):
            d = dt
        else:
            try:
                d = datetime.fromisoformat(str(dt)).date()
            except Exception:
                continue
        days_logged[d] = int(c.get("cigarettes_count", 0) or 0)

    current_streak = 0
    smoke_free_days = 0
    for i in range(days_since_quit + 1):
        d = quit_date + timedelta(days=i) if quit_date else today
        cigs = days_logged.get(d, None)
        if cigs is not None and cigs == 0:
            smoke_free_days += 1

    if quit_date:
        d = today
        while d >= quit_date:
            cigs = days_logged.get(d, None)
            if cigs == 0:
                current_streak += 1
                d -= timedelta(days=1)
                continue
            break

    cost_per_cig = price_per_pack / cigs_per_pack if cigs_per_pack else 0
    expected_spend = baseline_daily * cost_per_cig

    total_cigs_logged = sum([cnt for cnt in days_logged.values() if isinstance(cnt, int)])
    total_days = max(days_since_quit + 1, 1)
    cigs_avoided = max(baseline_daily * total_days - total_cigs_logged, 0)
    savings = round(cigs_avoided * cost_per_cig, 2)

    milestones = [1, 3, 7, 14, 30, 60, 90]
    progress = min((days_since_quit / max(milestones)) * 100, 100) if milestones else 0

    return {
        "days_since_quit": max(days_since_quit, 0),
        "current_streak": current_streak,
        "smoke_free_days": smoke_free_days,
        "savings": {"amount": savings, "currency": currency},
        "baseline_daily": baseline_daily,
        "expected_daily_spend": round(expected_spend, 2),
        "milestones": milestones,
        "progress": progress,
    }


def _badge_exists(user_id: str, key: str) -> bool:
    return _collection("badge").find_one({"user_id": user_id, "key": key}) is not None


def _award_badge(user_id: str, key: str, name: str, description: str, icon: str = "⭐"):
    if _badge_exists(user_id, key):
        return
    create_document(
        "badge",
        Badge(
            user_id=user_id,
            key=key,
            name=name,
            description=description,
            icon=icon,
            awarded_at=datetime.now(timezone.utc),
        ),
    )


def _maybe_award_badges(user_id: str, stats: Optional[Dict[str, Any]] = None):
    user = _ensure_user(user_id)
    if stats is None:
        stats = _compute_stats(user)
    days = stats.get("days_since_quit", 0)
    streak = stats.get("current_streak", 0)
    savings = stats.get("savings", {}).get("amount", 0)

    milestones = [1, 3, 7, 14, 30, 60, 90]
    for m in milestones:
        if days >= m:
            _award_badge(user_id, f"days_{m}", f"{m} dia(s) sem fumar", f"Você alcançou {m} dia(s) sem fumar!", "🔥")
    for m in [3, 7, 14, 30, 60]:
        if streak >= m:
            _award_badge(user_id, f"streak_{m}", f"Streak {m} dias", f"{m} dias consecutivos sem fumar", "🏆")
    for m in [10, 50, 100, 250, 500]:
        if savings >= m:
            _award_badge(user_id, f"savings_{m}", f"Economizou {user.get('currency', '$')}{m}", f"Você economizou pelo menos {user.get('currency', '$')}{m}", "💰")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
