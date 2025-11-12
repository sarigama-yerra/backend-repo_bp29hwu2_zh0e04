"""
Database Schemas for Quit Smoking Gamified App

Each Pydantic model represents a MongoDB collection. The collection name
is the lowercase of the class name.
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import date, datetime

class Userprofile(BaseModel):
    """
    Collection: userprofile
    Stores a user's quit plan and economic parameters to compute savings
    """
    name: str = Field(..., description="User display name")
    quit_date: date = Field(..., description="Target quit date (start of smoke-free period)")
    daily_cig_before: int = Field(..., ge=0, le=100, description="Average cigarettes per day before quitting")
    price_per_pack: float = Field(..., ge=0, description="Price per pack in user's currency")
    cigs_per_pack: int = Field(20, ge=1, le=40, description="Cigarettes per pack")
    currency: str = Field("$", description="Currency symbol for UI")

class Checkin(BaseModel):
    """
    Collection: checkin
    One per day per user; cigarettes_count=0 awards streak progress
    """
    user_id: str = Field(..., description="User id (stringified ObjectId)")
    date: date = Field(..., description="Calendar date of this check-in (UTC)")
    cigarettes_count: int = Field(0, ge=0, le=200, description="Number of cigarettes smoked on this date")

class Craving(BaseModel):
    """
    Collection: craving
    Track craving episodes for insights and coping strategies
    """
    user_id: str = Field(..., description="User id (stringified ObjectId)")
    intensity: int = Field(..., ge=1, le=5, description="Craving intensity 1-5")
    trigger: Optional[str] = Field(None, description="Trigger such as stress, coffee, social, alcohol")
    note: Optional[str] = Field(None, description="Optional note or coping action")
    occurred_at: Optional[datetime] = Field(None, description="When it happened; defaults to now")

class Badge(BaseModel):
    """
    Collection: badge
    Awarded achievements for motivation
    """
    user_id: str = Field(..., description="User id (stringified ObjectId)")
    key: str = Field(..., description="Unique badge key, e.g., streak_7, first_day, savings_50")
    name: str = Field(..., description="Badge display name")
    description: str = Field(..., description="What the user achieved")
    icon: str = Field("⭐", description="Simple icon or emoji for UI")
    awarded_at: datetime = Field(..., description="When awarded")

# Tip: The /schema endpoint in the backend can read these models if needed.
