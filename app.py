import os
import json
import secrets
import smtplib
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from calendar import monthrange
from io import BytesIO
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, send_file, session, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event, inspect, or_, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from werkzeug.security import check_password_hash, generate_password_hash


def load_env_file():
    env_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-before-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///travel.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"timeout": 30}}
app.config["OTP_TTL_SECONDS"] = int(os.environ.get("OTP_TTL_SECONDS", "600"))
app.config["OTP_RESEND_SECONDS"] = int(os.environ.get("OTP_RESEND_SECONDS", "60"))
app.config["OTP_MAX_ATTEMPTS"] = int(os.environ.get("OTP_MAX_ATTEMPTS", "5"))
app.config["SMTP_HOST"] = os.environ.get("SMTP_HOST", "smtp.gmail.com")
app.config["SMTP_PORT"] = int(os.environ.get("SMTP_PORT", "587"))
app.config["SMTP_USERNAME"] = os.environ.get("SMTP_USERNAME")
app.config["SMTP_PASSWORD"] = os.environ.get("SMTP_PASSWORD")
app.config["SMTP_FROM"] = os.environ.get("SMTP_FROM")
app.config["SMTP_USE_TLS"] = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
app.config["APP_ENV"] = os.environ.get("APP_ENV", "development").lower()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = app.config["APP_ENV"] == "production"
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
os.makedirs(app.instance_path, exist_ok=True)
db = SQLAlchemy(app)


@event.listens_for(Engine, "connect")
def configure_sqlite_connection(connection, connection_record):
    if connection.__class__.__module__.startswith("sqlite3"):
        cursor = connection.cursor()
        cursor.execute("PRAGMA busy_timeout=30000")
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            # A viewer may temporarily hold the database; retry configuration on a later connection.
            pass
        cursor.close()

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    phone_number = db.Column(db.String(30), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    preference = db.relationship("UserPreference", backref="user", uselist=False, cascade="all, delete-orphan")
    itineraries = db.relationship("Itinerary", backref="user", lazy=True, cascade="all, delete-orphan")


class UserPreference(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    travel_style = db.Column(db.String(30), default="Budget")
    interests = db.Column(db.String(500), default="Nature,Food")
    hotel_preference = db.Column(db.String(30), default="Budget")
    maximum_budget = db.Column(db.Float, default=30000)


class PendingSignup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    otp_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    last_sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    attempts = db.Column(db.Integer, default=0, nullable=False)


class PasswordReset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    otp_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, default=0, nullable=False)


class FavoriteDestination(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    destination_id = db.Column(db.Integer, db.ForeignKey("destination.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint("user_id", "destination_id", name="uq_user_favorite_destination"),)


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    destination_id = db.Column(db.Integer, db.ForeignKey("destination.id"), nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=False)
    body = db.Column(db.String(600), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint("user_id", "destination_id", name="uq_user_destination_review"),)


class PackingItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    itinerary_id = db.Column(db.Integer, db.ForeignKey("itinerary.id"), nullable=True, index=True)
    label = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(60), default="Essentials", nullable=False)
    completed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    itinerary_id = db.Column(db.Integer, db.ForeignKey("itinerary.id"), nullable=False, index=True)
    category = db.Column(db.String(60), nullable=False)
    description = db.Column(db.String(180), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    spent_at = db.Column(db.Date, default=date.today, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    kind = db.Column(db.String(40), default="general", nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class SupportTicket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), nullable=False, index=True)
    category = db.Column(db.String(60), nullable=False)
    subject = db.Column(db.String(180), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default="Open", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ItineraryShare(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    itinerary_id = db.Column(db.Integer, db.ForeignKey("itinerary.id"), nullable=False, unique=True)
    token = db.Column(db.String(96), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = db.Column(db.DateTime, nullable=True)
    itinerary = db.relationship("Itinerary", backref=db.backref("share", uselist=False))


class Destination(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    city_name = db.Column(db.String(100), unique=True, nullable=False)
    state = db.Column(db.String(100), nullable=False)
    country = db.Column(db.String(100), default="India")
    description = db.Column(db.Text, nullable=False)
    best_time_to_visit = db.Column(db.String(100), nullable=False)
    average_daily_cost = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(60), nullable=False)
    popularity_score = db.Column(db.Integer, default=75)
    image_url = db.Column(db.String(500), default="https://images.unsplash.com/photo-1524492412937-b28074a5d7da?auto=format&fit=crop&w=900&q=80")
    hotels = db.relationship("Hotel", backref="destination", lazy=True, cascade="all, delete-orphan")
    attractions = db.relationship("Attraction", backref="destination", lazy=True, cascade="all, delete-orphan")


class TransportOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    source_city = db.Column(db.String(100), nullable=False, index=True)
    destination_city = db.Column(db.String(100), nullable=False, index=True)
    transport_type = db.Column(db.String(30), nullable=False)
    provider_name = db.Column(db.String(120), nullable=False)
    departure_time = db.Column(db.String(20), nullable=False)
    arrival_time = db.Column(db.String(20), nullable=False)
    duration_hours = db.Column(db.Float, nullable=False)
    price_per_person = db.Column(db.Float, nullable=False)
    class_type = db.Column(db.String(50), nullable=False)
    rating = db.Column(db.Float, default=4.0)


class Hotel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    destination_id = db.Column(db.Integer, db.ForeignKey("destination.id"), nullable=False)
    hotel_name = db.Column(db.String(150), nullable=False)
    hotel_category = db.Column(db.String(30), nullable=False)
    price_per_night = db.Column(db.Float, nullable=False)
    rating = db.Column(db.Float, default=4.0)
    amenities = db.Column(db.String(400), default="Wi-Fi, Breakfast")
    address = db.Column(db.String(255), default="City Centre")
    image_url = db.Column(db.String(500), default="https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=900&q=80")
    available_rooms = db.Column(db.Integer, default=10)


class Attraction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    destination_id = db.Column(db.Integer, db.ForeignKey("destination.id"), nullable=False)
    attraction_name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(70), nullable=False)
    description = db.Column(db.Text, nullable=False)
    entry_fee = db.Column(db.Float, default=0)
    estimated_duration_hours = db.Column(db.Float, default=2)
    rating = db.Column(db.Float, default=4.0)
    opening_time = db.Column(db.String(20), default="09:00")
    closing_time = db.Column(db.String(20), default="18:00")
    image_url = db.Column(db.String(500), default="https://images.unsplash.com/photo-1501785888041-af3ef285b470?auto=format&fit=crop&w=900&q=80")


class Itinerary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    source_city = db.Column(db.String(100), nullable=False)
    destination_city = db.Column(db.String(100), nullable=False)
    departure_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date, nullable=False)
    travelers = db.Column(db.Integer, nullable=False)
    budget = db.Column(db.Float, nullable=False)
    total_cost = db.Column(db.Float, nullable=False)
    plan_name = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(30), default="Confirmed")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship("ItineraryItem", backref="itinerary", lazy=True, cascade="all, delete-orphan")
    bookings = db.relationship("Booking", backref="itinerary", lazy=True, cascade="all, delete-orphan")


class ItineraryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    itinerary_id = db.Column(db.Integer, db.ForeignKey("itinerary.id"), nullable=False)
    day_number = db.Column(db.Integer, default=1)
    category = db.Column(db.String(40), nullable=False)
    item_name = db.Column(db.String(180), nullable=False)
    details = db.Column(db.Text, default="")
    cost = db.Column(db.Float, default=0)


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    itinerary_id = db.Column(db.Integer, db.ForeignKey("itinerary.id"), nullable=False)
    booking_type = db.Column(db.String(40), nullable=False)
    item_name = db.Column(db.String(180), nullable=False)
    hotel_id = db.Column(db.Integer, db.ForeignKey("hotel.id"), nullable=True)
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)
    number_of_people = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    booking_status = db.Column(db.String(30), default="Confirmed")
    booking_reference = db.Column(db.String(24), unique=True, index=True, nullable=True)
    refund_amount = db.Column(db.Float, default=0, nullable=True)
    refund_status = db.Column(db.String(30), default="Not requested", nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def rupee(value):
    return f"₹{value:,.0f}"


app.jinja_env.filters["rupee"] = rupee


def destination_by_city(city):
    return Destination.query.filter_by(city_name=city).first()


def search_world_cities(query, limit=8):
    """Return worldwide city matches from Open-Meteo's free geocoding service."""
    query = query.strip()
    if len(query) < 2:
        return []
    request = Request(
        f"https://geocoding-api.open-meteo.com/v1/search?name={quote_plus(query)}&count={limit}&language=en&format=json",
        headers={"User-Agent": "Roamwise Travel Planner/1.0"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError):
        return []
    return [
        {
            "name": item.get("name"),
            "country": item.get("country", ""),
            "admin1": item.get("admin1", ""),
            "latitude": item.get("latitude"),
            "longitude": item.get("longitude"),
        }
        for item in payload.get("results", [])
        if item.get("name")
    ]


def ensure_world_destination(city):
    """Create generic local inventory for a valid worldwide city when needed."""
    existing = destination_by_city(city)
    if existing:
        return existing
    matches = search_world_cities(city, limit=1)
    if not matches:
        return None
    match = matches[0]
    destination = Destination(
        city_name=match["name"],
        state=match.get("admin1") or match.get("country") or "International",
        country=match.get("country") or "International",
        description=f"A Roamwise trip to {match['name']}, {match.get('country', '')}.",
        best_time_to_visit="Check local seasonal conditions",
        average_daily_cost=6500,
        category="International",
        popularity_score=70,
        image_url="https://images.unsplash.com/photo-1488646953014-85cb44e25828?auto=format&fit=crop&w=1200&q=80",
    )
    db.session.add(destination)
    db.session.flush()
    for hotel_type, price, rating in (("Budget", 3500, 4.0), ("Standard", 7000, 4.3), ("Luxury", 14000, 4.7)):
        db.session.add(Hotel(
            destination_id=destination.id,
            hotel_name=f"{match['name']} {hotel_type} Stay",
            hotel_category=hotel_type,
            price_per_night=price,
            rating=rating,
            amenities="Wi-Fi, Breakfast, City transfer",
            address="City centre",
            available_rooms=10,
        ))
    db.session.add(Attraction(
        destination_id=destination.id,
        attraction_name=f"{match['name']} city highlights",
        category="Sightseeing",
        description=f"Explore the most popular sights and neighbourhoods around {match['name']}.",
        entry_fee=1200,
        rating=4.3,
    ))
    db.session.commit()
    return destination


def create_notification(user_id, title, message, kind="general"):
    db.session.add(Notification(user_id=user_id, title=title, message=message, kind=kind))


def generate_booking_reference():
    """Generate a short, user-facing reference without relying on a database sequence."""
    return f"RW-{secrets.token_hex(6).upper()}"


def calculate_refund(booking, as_of=None):
    """Return the simulated refund amount and policy status for a booking."""
    if booking.booking_status == "Cancelled":
        return float(booking.refund_amount or 0), booking.refund_status or "Processed"
    as_of = as_of or date.today()
    days_until_departure = (booking.itinerary.departure_date - as_of).days
    if days_until_departure >= 7:
        return float(booking.total_price), "Full refund"
    if days_until_departure >= 3:
        return round(float(booking.total_price) * 0.5, 2), "50% refund"
    return 0.0, "No refund"


def send_transaction_email(recipient, subject, body):
    """Send booking notifications through the configured SMTP provider."""
    required = ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM")
    if not all(app.config[key] for key in required):
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = app.config["SMTP_FROM"]
    message["To"] = recipient
    message.set_content(body)
    with smtplib.SMTP(app.config["SMTP_HOST"], app.config["SMTP_PORT"], timeout=10) as client:
        if app.config["SMTP_USE_TLS"]:
            client.starttls()
        client.login(app.config["SMTP_USERNAME"], app.config["SMTP_PASSWORD"])
        client.send_message(message)
    return True


def create_departure_reminders(user_id):
    """Create at most one in-app reminder for each upcoming itinerary."""
    today = date.today()
    upcoming = Itinerary.query.filter(
        Itinerary.user_id == user_id,
        Itinerary.status == "Confirmed",
        Itinerary.departure_date >= today,
        Itinerary.departure_date <= today + timedelta(days=3),
    ).all()
    created = False
    for itinerary in upcoming:
        title = "Departure reminder"
        message = f"Your trip to {itinerary.destination_city} departs on {itinerary.departure_date:%d %b %Y}."
        if not Notification.query.filter_by(user_id=user_id, title=title, message=message).first():
            create_notification(user_id, title, message, "reminder")
            created = True
    return created


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        allowed = {email.strip().lower() for email in os.environ.get("ADMIN_EMAILS", "").split(",") if email.strip()}
        if current_user.email.lower() not in allowed:
            flash("Administrator access is required.", "danger")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped


def owned_itinerary(itinerary_id):
    itinerary = db.get_or_404(Itinerary, itinerary_id)
    if itinerary.user_id != current_user.id:
        flash("You cannot access another traveler’s itinerary.", "danger")
        return None
    return itinerary


CITY_COORDINATES = {
    "Delhi": (28.6139, 77.2090), "Mumbai": (19.0760, 72.8777), "Goa": (15.2993, 74.1240),
    "Jaipur": (26.9124, 75.7873), "Agra": (27.1767, 78.0081), "Manali": (32.2432, 77.1892),
    "Rishikesh": (30.0869, 78.2676), "Kochi": (9.9312, 76.2673), "Udaipur": (24.5854, 73.7125),
    "Varanasi": (25.3176, 82.9739), "Darjeeling": (27.0410, 88.2663), "Bengaluru": (12.9716, 77.5946),
}


def generate_otp():
    return f"{secrets.randbelow(1_000_000):06d}"


def send_otp_email(recipient, otp):
    """Send an OTP through SMTP, or save it to a local debug file in demo mode."""

    required = ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM")
    if not all(app.config[key] for key in required):
        debug_path = os.path.join(app.instance_path, "otp_debug.log")
        with open(debug_path, "a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}] {recipient} | otp={otp}\n")
        return False

    message = EmailMessage()
    message["Subject"] = "Your Roamwise verification code"
    message["From"] = app.config["SMTP_FROM"]
    message["To"] = recipient
    message.set_content(
        f"Your Roamwise verification code is {otp}. It expires in "
        f"{app.config['OTP_TTL_SECONDS'] // 60} minutes. Do not share this code."
    )
    with smtplib.SMTP(app.config["SMTP_HOST"], app.config["SMTP_PORT"], timeout=10) as client:
        if app.config["SMTP_USE_TLS"]:
            client.starttls()
        client.login(app.config["SMTP_USERNAME"], app.config["SMTP_PASSWORD"])
        client.send_message(message)
    return True


def trip_options(source, destination, depart, returning, travelers, budget, style, interests, hotel_pref):
    """Compare three packages; the lowest-cost in-budget package is the budget recommendation."""
    dest = destination_by_city(destination)
    transport = TransportOption.query.filter_by(source_city=source, destination_city=destination).all()
    hotels = Hotel.query.filter_by(destination_id=dest.id).filter(Hotel.available_rooms > 0).all() if dest else []
    attractions = Attraction.query.filter_by(destination_id=dest.id).all() if dest else []
    if not transport and dest and hotels:
        transport = [TransportOption(source_city=source, destination_city=destination, transport_type="Flight", provider_name="Roamwise route estimate", departure_time="09:00", arrival_time="12:00", duration_hours=3.0, price_per_person=4500, class_type="Economy", rating=4.0)]
    if not hotels:
        return []

    days = max((returning - depart).days, 1)
    interest_set = {item.strip().lower() for item in interests if item}
    matching = [a for a in attractions if a.category.lower() in interest_set]
    activities = matching or attractions
    styles = [("Budget", "Budget"), ("Standard", "Standard"), ("Luxury", "Luxury")]
    packages = []
    food_daily = {"Budget": 800, "Standard": 1500, "Luxury": 3000}

    for package_name, hotel_type in styles:
        if package_name == "Budget":
            chosen_transport = min(transport, key=lambda x: x.price_per_person)
            chosen_hotel = min([h for h in hotels if h.hotel_category == hotel_type] or hotels, key=lambda x: x.price_per_night)
            chosen_activities = sorted(activities, key=lambda x: (x.entry_fee, -x.rating))[:min(days, 3)]
        elif package_name == "Standard":
            chosen_transport = max(transport, key=lambda x: (x.rating * 100 - x.price_per_person / 100, -x.duration_hours))
            pool = [h for h in hotels if h.hotel_category == hotel_type] or hotels
            chosen_hotel = max(pool, key=lambda x: x.rating * 100 - x.price_per_night / 200)
            chosen_activities = sorted(activities, key=lambda x: (-x.rating, x.entry_fee))[:min(days, 3)]
        else:
            chosen_transport = max(transport, key=lambda x: (x.rating, x.price_per_person))
            pool = [h for h in hotels if h.hotel_category == hotel_type] or hotels
            chosen_hotel = max(pool, key=lambda x: (x.rating, x.price_per_night))
            chosen_activities = sorted(activities, key=lambda x: (-x.rating, -x.entry_fee))[:min(days, 3)]

        transport_cost = chosen_transport.price_per_person * travelers
        hotel_cost = chosen_hotel.price_per_night * days
        activity_cost = sum(a.entry_fee for a in chosen_activities) * travelers
        food_cost = food_daily[package_name] * travelers * days
        local_cost = 400 * travelers * days
        total = transport_cost + hotel_cost + activity_cost + food_cost + local_cost
        interest_match = min(len(chosen_activities), len(interest_set)) / max(len(interest_set), 1)
        budget_fit = min(1, budget / total) if total else 1
        popularity = dest.popularity_score / 100
        score = round(interest_match * 40 + (chosen_hotel.rating / 5) * 20 + budget_fit * 30 + popularity * 10, 1)
        packages.append({
            "name": package_name, "transport": chosen_transport, "hotel": chosen_hotel,
            "activities": chosen_activities, "days": days, "transport_cost": transport_cost,
            "hotel_cost": hotel_cost, "activity_cost": activity_cost, "food_cost": food_cost,
            "local_cost": local_cost, "total": total, "remaining": budget - total,
            "score": score, "within_budget": total <= budget,
        })
    packages.sort(key=lambda item: (not item["within_budget"], item["total"], -item["score"]))
    return packages


@app.route("/")
def home():
    destinations = Destination.query.order_by(Destination.popularity_score.desc()).limit(6).all()
    return render_template("home.html", destinations=destinations)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if not name or not email or not password:
            flash("Please complete every required field.", "danger")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "danger")
        elif password != confirm or len(password) < 6:
            flash("Passwords must match and be at least 6 characters.", "danger")
        else:
            otp = generate_otp()
            pending = PendingSignup.query.filter_by(email=email).first()
            if not pending:
                pending = PendingSignup(email=email)
                db.session.add(pending)
            pending.name = name
            pending.password_hash = generate_password_hash(password)
            pending.otp_hash = generate_password_hash(otp)
            pending.expires_at = datetime.utcnow() + timedelta(seconds=app.config["OTP_TTL_SECONDS"])
            pending.last_sent_at = datetime.utcnow()
            pending.attempts = 0
            try:
                email_sent = send_otp_email(email, otp)
            except (OSError, smtplib.SMTPException):
                db.session.rollback()
                flash("We could not send a verification code. Please try again later.", "danger")
            else:
                db.session.commit()
                session["pending_signup_email"] = email
                if email_sent:
                    flash("We sent a six-digit verification code to your email.", "info")
                else:
                    flash("Gmail SMTP is not configured. Add your SMTP credentials to .env and restart the app to send real OTP emails.", "warning")
                return redirect(url_for("verify_signup"))
    return render_template("signup.html")


@app.route("/verify-signup", methods=["GET", "POST"])
def verify_signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    email = session.get("pending_signup_email")
    pending = PendingSignup.query.filter_by(email=email).first() if email else None
    if not pending:
        flash("Start by creating an account.", "warning")
        return redirect(url_for("signup"))
    if request.method == "POST":
        code = request.form.get("otp", "").strip()
        if pending.expires_at < datetime.utcnow():
            db.session.delete(pending)
            db.session.commit()
            session.pop("pending_signup_email", None)
            flash("That verification code expired. Please sign up again.", "warning")
            return redirect(url_for("signup"))
        if pending.attempts >= app.config["OTP_MAX_ATTEMPTS"]:
            db.session.delete(pending)
            db.session.commit()
            session.pop("pending_signup_email", None)
            flash("Too many incorrect codes. Please sign up again.", "danger")
            return redirect(url_for("signup"))
        if not (code.isdigit() and len(code) == 6 and check_password_hash(pending.otp_hash, code)):
            pending.attempts += 1
            db.session.commit()
            flash("That verification code is invalid.", "danger")
        else:
            user = User(name=pending.name, email=pending.email, password_hash=pending.password_hash)
            db.session.add(user)
            db.session.flush()
            db.session.add(UserPreference(user_id=user.id))
            db.session.delete(pending)
            db.session.commit()
            session.pop("pending_signup_email", None)
            login_user(user)
            flash("Email verified. Your account is ready!", "success")
            return redirect(url_for("dashboard"))
    return render_template("verify_signup.html", email=pending.email)


@app.route("/verify-signup/resend", methods=["POST"])
def resend_signup_otp():
    email = session.get("pending_signup_email")
    pending = PendingSignup.query.filter_by(email=email).first() if email else None
    if not pending:
        flash("Start by creating an account.", "warning")
        return redirect(url_for("signup"))
    elapsed = (datetime.utcnow() - pending.last_sent_at).total_seconds()
    if elapsed < app.config["OTP_RESEND_SECONDS"]:
        flash("Please wait a minute before requesting another code.", "warning")
        return redirect(url_for("verify_signup"))
    otp = generate_otp()
    pending.otp_hash = generate_password_hash(otp)
    pending.expires_at = datetime.utcnow() + timedelta(seconds=app.config["OTP_TTL_SECONDS"])
    pending.last_sent_at = datetime.utcnow()
    pending.attempts = 0
    try:
        email_sent = send_otp_email(pending.email, otp)
    except (OSError, smtplib.SMTPException):
        db.session.rollback()
        flash("We could not send a new verification code. Please try again later.", "danger")
    else:
        db.session.commit()
        if email_sent:
            flash("A new verification code has been sent.", "info")
        else:
            flash("Gmail SMTP is not configured. Add your SMTP credentials to .env and restart the app to send real OTP emails.", "warning")
    return redirect(url_for("verify_signup"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, request.form.get("password", "")):
            login_user(user)
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            otp = generate_otp()
            reset = PasswordReset.query.filter_by(email=email).first()
            if not reset:
                reset = PasswordReset(email=email)
                db.session.add(reset)
            reset.otp_hash = generate_password_hash(otp)
            reset.expires_at = datetime.utcnow() + timedelta(seconds=app.config["OTP_TTL_SECONDS"])
            reset.attempts = 0
            try:
                email_sent = send_otp_email(email, otp)
            except (OSError, smtplib.SMTPException):
                db.session.rollback()
                flash("We could not send a reset code. Please try again later.", "danger")
            else:
                db.session.commit()
                session["password_reset_email"] = email
                if email_sent:
                    flash("If that email belongs to an account, a reset code has been sent.", "info")
                else:
                    flash("Gmail SMTP is not configured. Add your SMTP credentials to .env and restart the app to send real OTP emails.", "warning")
                return redirect(url_for("reset_password"))
        else:
            flash("If that email belongs to an account, a reset code has been sent.", "info")
    return render_template("forgot_password.html")


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    email = session.get("password_reset_email")
    reset = PasswordReset.query.filter_by(email=email).first() if email else None
    if not reset:
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        code = request.form.get("otp", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if reset.expires_at < datetime.utcnow():
            db.session.delete(reset)
            db.session.commit()
            session.pop("password_reset_email", None)
            flash("That reset code expired. Please request a new one.", "warning")
            return redirect(url_for("forgot_password"))
        if reset.attempts >= app.config["OTP_MAX_ATTEMPTS"]:
            db.session.delete(reset)
            db.session.commit()
            session.pop("password_reset_email", None)
            flash("Too many incorrect codes. Please request a new one.", "danger")
            return redirect(url_for("forgot_password"))
        if not (code.isdigit() and len(code) == 6 and check_password_hash(reset.otp_hash, code)):
            reset.attempts += 1
            db.session.commit()
            flash("That reset code is invalid.", "danger")
        elif len(password) < 6 or password != confirm:
            flash("Passwords must match and be at least 6 characters.", "danger")
        else:
            user = User.query.filter_by(email=email).first()
            user.password_hash = generate_password_hash(password)
            db.session.delete(reset)
            db.session.commit()
            session.pop("password_reset_email", None)
            flash("Your password has been updated. You can log in now.", "success")
            return redirect(url_for("login"))
    return render_template("reset_password.html", email=email)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not check_password_hash(current_user.password_hash, current_password):
            flash("Your current password is incorrect.", "danger")
        elif len(new_password) < 8 or new_password != confirm_password:
            flash("New passwords must match and be at least 8 characters.", "danger")
        elif check_password_hash(current_user.password_hash, new_password):
            flash("Choose a password different from your current password.", "danger")
        else:
            current_user.password_hash = generate_password_hash(new_password)
            db.session.commit()
            flash("Your password has been changed.", "success")
            return redirect(url_for("profile"))
    return render_template("change_password.html")


@app.route("/dashboard")
@login_required
def dashboard():
    if create_departure_reminders(current_user.id):
        db.session.commit()
    itineraries = Itinerary.query.filter_by(user_id=current_user.id).order_by(Itinerary.created_at.desc()).limit(4).all()
    destinations = Destination.query.order_by(Destination.popularity_score.desc()).limit(4).all()
    upcoming = [trip for trip in itineraries if trip.return_date >= date.today()]
    total_spend = sum(trip.total_cost for trip in Itinerary.query.filter_by(user_id=current_user.id).all())
    favorite_ids = [item.destination_id for item in FavoriteDestination.query.filter_by(user_id=current_user.id).all()]
    favorites = Destination.query.filter(Destination.id.in_(favorite_ids)).order_by(Destination.popularity_score.desc()).limit(4).all() if favorite_ids else []
    unread_notifications = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return render_template("dashboard.html", itineraries=itineraries, destinations=destinations, upcoming=upcoming,
                           total_spend=total_spend, favorites=favorites, unread_notifications=unread_notifications)


@app.route("/favorites")
@login_required
def favorites():
    favorite_ids = [item.destination_id for item in FavoriteDestination.query.filter_by(user_id=current_user.id).all()]
    saved_destinations = Destination.query.filter(Destination.id.in_(favorite_ids)).order_by(Destination.city_name).all() if favorite_ids else []
    return render_template("favorites.html", destinations=saved_destinations)


@app.route("/packing", methods=["GET", "POST"])
@login_required
def packing_list():
    if request.method == "POST":
        label = request.form.get("label", "").strip()
        category = request.form.get("category", "Essentials").strip()[:60] or "Essentials"
        itinerary_id = request.form.get("itinerary_id", type=int)
        if not label or len(label) > 180:
            flash("Enter an item up to 180 characters.", "danger")
        elif itinerary_id and not Itinerary.query.filter_by(id=itinerary_id, user_id=current_user.id).first():
            flash("Choose one of your own itineraries.", "danger")
        else:
            db.session.add(PackingItem(user_id=current_user.id, itinerary_id=itinerary_id, label=label, category=category))
            db.session.commit()
            flash("Packing item added.", "success")
        return redirect(url_for("packing_list"))
    items = PackingItem.query.filter_by(user_id=current_user.id).order_by(PackingItem.completed, PackingItem.category, PackingItem.created_at.desc()).all()
    trips = Itinerary.query.filter_by(user_id=current_user.id).order_by(Itinerary.departure_date.desc()).all()
    return render_template("packing.html", items=items, itineraries=trips)


@app.route("/packing/generate/<int:itinerary_id>", methods=["POST"])
@login_required
def generate_packing_items(itinerary_id):
    itinerary = Itinerary.query.filter_by(id=itinerary_id, user_id=current_user.id).first_or_404()
    days = max((itinerary.return_date - itinerary.departure_date).days, 1)
    defaults = [
        ("Government ID and copies", "Documents"), ("Booking confirmations", "Documents"),
        ("Phone charger and power bank", "Essentials"), ("Toiletries", "Essentials"),
        ("Comfortable walking shoes", "Clothing"), ("Weather-appropriate clothes", "Clothing"),
        ("Basic medicines", "Health"), ("Reusable water bottle", "Activities"),
    ]
    if days >= 5:
        defaults.append(("Laundry bag", "Clothing"))
    existing = {item.label for item in PackingItem.query.filter_by(user_id=current_user.id, itinerary_id=itinerary.id).all()}
    added = 0
    for label, category in defaults:
        if label not in existing:
            db.session.add(PackingItem(user_id=current_user.id, itinerary_id=itinerary.id, label=label, category=category))
            added += 1
    db.session.commit()
    flash(f"Added {added} smart packing item(s) for your {itinerary.destination_city} trip.", "success")
    return redirect(url_for("packing_list"))


@app.route("/packing/<int:item_id>/toggle", methods=["POST"])
@login_required
def toggle_packing_item(item_id):
    item = PackingItem.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    item.completed = not item.completed
    db.session.commit()
    return redirect(url_for("packing_list"))


@app.route("/packing/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_packing_item(item_id):
    item = PackingItem.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash("Packing item removed.", "info")
    return redirect(url_for("packing_list"))


@app.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses():
    trips = Itinerary.query.filter_by(user_id=current_user.id).order_by(Itinerary.departure_date.desc()).all()
    if request.method == "POST":
        itinerary_id = request.form.get("itinerary_id", type=int)
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "Other").strip()[:60] or "Other"
        try:
            amount = float(request.form.get("amount", "0"))
            spent_at = datetime.strptime(request.form.get("spent_at"), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            amount, spent_at = 0, None
        itinerary = Itinerary.query.filter_by(id=itinerary_id, user_id=current_user.id).first()
        if not itinerary or not description or len(description) > 180 or amount <= 0 or spent_at is None:
            flash("Choose your trip and enter a valid expense.", "danger")
        else:
            db.session.add(Expense(user_id=current_user.id, itinerary_id=itinerary.id, category=category, description=description, amount=amount, spent_at=spent_at))
            db.session.commit()
            flash("Expense added to your trip budget.", "success")
        return redirect(url_for("expenses"))
    selected_id = request.args.get("itinerary_id", type=int)
    selected = next((trip for trip in trips if trip.id == selected_id), trips[0] if trips else None)
    rows = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.spent_at.desc(), Expense.created_at.desc()).all()
    spent_by_trip = {trip.id: sum(item.amount for item in rows if item.itinerary_id == trip.id) for trip in trips}
    return render_template("expenses.html", itineraries=trips, selected_itinerary=selected, expenses=rows, spent_by_trip=spent_by_trip, today=date.today().isoformat())


@app.route("/expenses/<int:expense_id>/delete", methods=["POST"])
@login_required
def delete_expense(expense_id):
    expense = Expense.query.filter_by(id=expense_id, user_id=current_user.id).first_or_404()
    db.session.delete(expense)
    db.session.commit()
    flash("Expense removed.", "info")
    return redirect(url_for("expenses"))


@app.route("/notifications")
@login_required
def notifications():
    if create_departure_reminders(current_user.id):
        db.session.commit()
    items = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    for item in items:
        item.is_read = True
    db.session.commit()
    return render_template("notifications.html", notifications=items)


@app.route("/destinations")
def destinations():
    category = request.args.get("category", "")
    search = request.args.get("q", "").strip()
    max_budget = request.args.get("max_budget", type=float)
    query = Destination.query
    if category:
        query = query.filter_by(category=category)
    if search:
        query = query.filter(or_(Destination.city_name.ilike(f"%{search}%"), Destination.state.ilike(f"%{search}%"), Destination.category.ilike(f"%{search}%")))
    if max_budget:
        query = query.filter(Destination.average_daily_cost <= max_budget)
    return render_template("destinations.html", destinations=query.order_by(Destination.popularity_score.desc()).all(), category=category, search=search, max_budget=max_budget)


@app.route("/destinations/<int:destination_id>")
def destination_detail(destination_id):
    dest = db.get_or_404(Destination, destination_id)
    favorite = current_user.is_authenticated and FavoriteDestination.query.filter_by(user_id=current_user.id, destination_id=dest.id).first()
    reviews = Review.query.filter_by(destination_id=dest.id).order_by(Review.created_at.desc()).all()
    average_rating = round(sum(review.rating for review in reviews) / len(reviews), 1) if reviews else None
    return render_template("destination_detail.html", destination=dest, favorite=bool(favorite), reviews=reviews, average_rating=average_rating, coordinates=CITY_COORDINATES.get(dest.city_name))


@app.route("/destinations/<int:destination_id>/favorite", methods=["POST"])
@login_required
def toggle_favorite(destination_id):
    db.get_or_404(Destination, destination_id)
    favorite = FavoriteDestination.query.filter_by(user_id=current_user.id, destination_id=destination_id).first()
    if favorite:
        db.session.delete(favorite)
        flash("Removed from saved destinations.", "info")
    else:
        db.session.add(FavoriteDestination(user_id=current_user.id, destination_id=destination_id))
        flash("Saved to your favorite destinations.", "success")
    db.session.commit()
    return redirect(url_for("destination_detail", destination_id=destination_id))


@app.route("/destinations/<int:destination_id>/review", methods=["POST"])
@login_required
def save_review(destination_id):
    db.get_or_404(Destination, destination_id)
    rating = request.form.get("rating", type=int)
    body = request.form.get("body", "").strip()
    if rating not in range(1, 6) or not 10 <= len(body) <= 600:
        flash("Reviews need a 1-5 rating and 10-600 characters.", "danger")
        return redirect(url_for("destination_detail", destination_id=destination_id))
    review = Review.query.filter_by(user_id=current_user.id, destination_id=destination_id).first()
    if not review:
        review = Review(user_id=current_user.id, destination_id=destination_id, rating=rating, body=body)
        db.session.add(review)
    else:
        review.rating, review.body, review.created_at = rating, body, datetime.utcnow()
    db.session.commit()
    flash("Your review has been saved.", "success")
    return redirect(url_for("destination_detail", destination_id=destination_id))


@app.route("/planner", methods=["GET", "POST"])
@login_required
def planner():
    cities = [d.city_name for d in Destination.query.order_by(Destination.city_name).all()]
    if request.method == "POST":
        source_text = request.form.get("source", "").strip()
        destination_text = request.form.get("destination", "").strip()
        source_match = Destination.query.filter(Destination.city_name.ilike(source_text)).first() if source_text else None
        destination_match = Destination.query.filter(Destination.city_name.ilike(destination_text)).first() if destination_text else None
        if not source_match and source_text:
            source_matches = search_world_cities(source_text, limit=1)
            source_text = source_matches[0]["name"] if source_matches else source_text
        if not destination_match and destination_text:
            destination_match = ensure_world_destination(destination_text)
        source = source_match.city_name if source_match else source_text
        destination = destination_match.city_name if destination_match else destination_text
        try:
            departure = datetime.strptime(request.form.get("departure_date"), "%Y-%m-%d").date()
            returning = datetime.strptime(request.form.get("return_date"), "%Y-%m-%d").date()
            travelers = int(request.form.get("travelers", 1))
            budget = float(request.form.get("budget", 0))
        except (TypeError, ValueError):
            flash("Enter valid travel dates, traveler count, and budget.", "danger")
            return render_template("planner.html", cities=cities, preference=current_user.preference, today=date.today().isoformat())
        interests = request.form.getlist("interests")
        if not destination_match:
            flash("We could not find that city. Select a city from the worldwide suggestions and try again.", "danger")
        elif source == destination or departure < date.today() or returning <= departure or travelers < 1 or budget <= 0:
            flash("Choose different cities, valid future dates, and a positive budget.", "danger")
        else:
            packages = trip_options(source, destination, departure, returning, travelers, budget, request.form.get("travel_style"), interests, request.form.get("hotel_preference"))
            if not packages:
                flash("We could not find enough options for that route. Try another route.", "warning")
            else:
                session["draft_trip"] = {
                    "source": source, "destination": destination, "departure": departure.isoformat(), "returning": returning.isoformat(),
                    "travelers": travelers, "budget": budget, "style": request.form.get("travel_style"), "interests": interests,
                    "hotel_preference": request.form.get("hotel_preference"),
                }
                return render_template("itinerary_result.html", packages=packages, trip=session["draft_trip"], destination=destination_by_city(destination))
    return render_template("planner.html", cities=cities, preference=current_user.preference, today=date.today().isoformat())


@app.route("/api/cities")
@login_required
def city_search():
    return {"results": search_world_cities(request.args.get("q", ""))}


@app.route("/book-package/<int:package_index>", methods=["POST"])
@login_required
def book_package(package_index):
    trip = session.get("draft_trip")
    if not trip:
        flash("Create an itinerary before booking it.", "warning")
        return redirect(url_for("planner"))
    departure = datetime.fromisoformat(trip["departure"]).date()
    returning = datetime.fromisoformat(trip["returning"]).date()
    packages = trip_options(trip["source"], trip["destination"], departure, returning, trip["travelers"], trip["budget"], trip["style"], trip["interests"], trip["hotel_preference"])
    if package_index < 0 or package_index >= len(packages):
        flash("That package is no longer available.", "danger")
        return redirect(url_for("planner"))
    p = packages[package_index]
    if p["hotel"].available_rooms < 1:
        flash("This hotel has sold out. Please choose another package.", "warning")
        return redirect(url_for("planner"))
    itinerary = Itinerary(user_id=current_user.id, source_city=trip["source"], destination_city=trip["destination"], departure_date=departure,
                          return_date=returning, travelers=trip["travelers"], budget=trip["budget"], total_cost=p["total"], plan_name=p["name"])
    db.session.add(itinerary)
    db.session.flush()
    entries = [
        (1, "Transport", f"{p['transport'].transport_type}: {p['transport'].provider_name}", f"{p['transport'].source_city} to {p['transport'].destination_city}", p["transport_cost"]),
        (1, "Hotel", p["hotel"].hotel_name, f"{p['days']} night(s), {p['hotel'].hotel_category}", p["hotel_cost"]),
        (1, "Food", "Estimated meals", f"{p['name']} food allowance", p["food_cost"]),
        (1, "Local Transport", "Estimated local travel", "Taxis, metro and local transit", p["local_cost"]),
    ]
    for pos, attraction in enumerate(p["activities"], start=1):
        entries.append((min(pos + 1, p["days"]), "Activity", attraction.attraction_name, attraction.description, attraction.entry_fee * trip["travelers"]))
    for day_no, category, item_name, details, cost in entries:
        db.session.add(ItineraryItem(itinerary_id=itinerary.id, day_number=day_no, category=category, item_name=item_name, details=details, cost=cost))
    bookings = [
        ("Transport", p["transport"].provider_name, None, p["transport_cost"]),
        ("Hotel", p["hotel"].hotel_name, p["hotel"].id, p["hotel_cost"]),
    ]
    for attraction in p["activities"]:
        bookings.append(("Activity", attraction.attraction_name, None, attraction.entry_fee * trip["travelers"]))
    for booking_type, item_name, hotel_id, amount in bookings:
        db.session.add(Booking(user_id=current_user.id, itinerary_id=itinerary.id, booking_type=booking_type, item_name=item_name,
                              hotel_id=hotel_id, number_of_people=trip["travelers"], total_price=amount,
                              booking_reference=generate_booking_reference(), refund_status="Not requested"))
    p["hotel"].available_rooms -= 1
    create_notification(current_user.id, "Trip confirmed", f"Your {trip['destination']} itinerary is ready to review.", "booking")
    db.session.commit()
    try:
        refs = ", ".join(booking.booking_reference for booking in itinerary.bookings)
        send_transaction_email(
            current_user.email,
            f"Roamwise booking confirmed · {trip['destination']}",
            f"Hi {current_user.name},\n\nYour trip from {trip['source']} to {trip['destination']} is confirmed "
            f"for {departure:%d %b %Y}–{returning:%d %b %Y}.\n"
            f"Booking references: {refs}\nTotal itinerary cost: {rupee(itinerary.total_cost)}\n\n"
            "You can download your itinerary and receipts from Roamwise.",
        )
    except (OSError, smtplib.SMTPException):
        app.logger.warning("Unable to send booking confirmation email", exc_info=True)
    session.pop("draft_trip", None)
    flash("Your itinerary and simulated bookings are confirmed!", "success")
    return redirect(url_for("itinerary_detail", itinerary_id=itinerary.id))


@app.route("/itineraries")
@login_required
def itineraries():
    trips = Itinerary.query.filter_by(user_id=current_user.id).order_by(Itinerary.created_at.desc()).all()
    return render_template("itineraries.html", itineraries=trips)


@app.route("/itinerary/<int:itinerary_id>")
@login_required
def itinerary_detail(itinerary_id):
    itinerary = db.get_or_404(Itinerary, itinerary_id)
    if itinerary.user_id != current_user.id:
        flash("You cannot view another traveler’s itinerary.", "danger")
        return redirect(url_for("dashboard"))
    return render_template("itinerary_detail.html", itinerary=itinerary, share=ItineraryShare.query.filter_by(itinerary_id=itinerary.id).first())


@app.route("/itinerary/<int:itinerary_id>/download")
@login_required
def download_itinerary(itinerary_id):
    itinerary = db.get_or_404(Itinerary, itinerary_id)
    if itinerary.user_id != current_user.id:
        flash("You cannot download another traveler’s itinerary.", "danger")
        return redirect(url_for("dashboard"))
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Roamwise itinerary", styles["Title"]),
        Spacer(1, 6),
        Paragraph(f"{itinerary.source_city} to {itinerary.destination_city} | {itinerary.departure_date:%d %b %Y} - {itinerary.return_date:%d %b %Y}", styles["Normal"]),
        Paragraph(f"{itinerary.travelers} traveler(s) | {itinerary.plan_name} package | Total: {rupee(itinerary.total_cost)}", styles["Normal"]),
        Spacer(1, 14),
    ]
    rows = [["Day", "Category", "Plan", "Cost"]]
    rows.extend([
        [str(item.day_number), item.category, Paragraph(f"<b>{item.item_name}</b><br/>{item.details}", styles["BodyText"]), rupee(item.cost)]
        for item in sorted(itinerary.items, key=lambda item: (item.day_number, item.id))
    ])
    table = Table(rows, colWidths=[15 * mm, 28 * mm, 105 * mm, 25 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b2637")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#c8d8d7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f8f7")]),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    document.build(story)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"roamwise-{itinerary.destination_city.lower()}-{itinerary.id}.pdf", mimetype="application/pdf")


@app.route("/itinerary/<int:itinerary_id>/share", methods=["POST"])
@login_required
def create_itinerary_share(itinerary_id):
    itinerary = owned_itinerary(itinerary_id)
    if not itinerary:
        return redirect(url_for("dashboard"))
    share = ItineraryShare.query.filter_by(itinerary_id=itinerary.id).first()
    if not share:
        share = ItineraryShare(itinerary_id=itinerary.id, token=secrets.token_urlsafe(48))
        db.session.add(share)
    share.revoked_at = None
    db.session.commit()
    flash("Private itinerary link created. Anyone with the link can view it.", "success")
    return redirect(url_for("itinerary_detail", itinerary_id=itinerary.id))


@app.route("/itinerary/<int:itinerary_id>/share/revoke", methods=["POST"])
@login_required
def revoke_itinerary_share(itinerary_id):
    itinerary = owned_itinerary(itinerary_id)
    if not itinerary:
        return redirect(url_for("dashboard"))
    share = ItineraryShare.query.filter_by(itinerary_id=itinerary.id).first()
    if share:
        share.revoked_at = datetime.utcnow()
        db.session.commit()
    flash("The shared link was revoked.", "info")
    return redirect(url_for("itinerary_detail", itinerary_id=itinerary.id))


@app.route("/shared/itinerary/<token>")
def shared_itinerary(token):
    share = ItineraryShare.query.filter_by(token=token).first_or_404()
    if share.revoked_at:
        return render_template("404.html"), 404
    return render_template("itinerary_public.html", itinerary=share.itinerary)


@app.route("/itinerary/<int:itinerary_id>/calendar")
@login_required
def download_itinerary_calendar(itinerary_id):
    itinerary = owned_itinerary(itinerary_id)
    if not itinerary:
        return redirect(url_for("dashboard"))
    start = itinerary.departure_date.strftime("%Y%m%d")
    end = (itinerary.return_date + timedelta(days=1)).strftime("%Y%m%d")
    summary = f"Roamwise trip to {itinerary.destination_city}"
    calendar_data = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Roamwise//Travel Planner//EN", "BEGIN:VEVENT",
        f"UID:roamwise-itinerary-{itinerary.id}@roamwise", f"DTSTAMP:{datetime.utcnow():%Y%m%dT%H%M%SZ}",
        f"DTSTART;VALUE=DATE:{start}", f"DTEND;VALUE=DATE:{end}", f"SUMMARY:{summary}",
        f"DESCRIPTION:{itinerary.plan_name} package for {itinerary.travelers} traveler(s)",
        f"LOCATION:{itinerary.destination_city}, India", "END:VEVENT", "END:VCALENDAR", "",
    ])
    return send_file(BytesIO(calendar_data.encode("utf-8")), as_attachment=True, download_name=f"roamwise-trip-{itinerary.id}.ics", mimetype="text/calendar")


@app.route("/booking/<int:booking_id>/receipt")
@login_required
def booking_receipt(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    if booking.user_id != current_user.id:
        flash("You cannot access another traveler’s receipt.", "danger")
        return redirect(url_for("bookings"))
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=22 * mm, leftMargin=22 * mm, topMargin=22 * mm, bottomMargin=22 * mm)
    styles = getSampleStyleSheet()
    story = [Paragraph("Roamwise booking receipt", styles["Title"]), Spacer(1, 12),
             Paragraph(f"Receipt #{booking.id:06d}", styles["Heading2"]),
             Paragraph(f"Traveler: {current_user.name} ({current_user.email})", styles["Normal"]),
             Paragraph(f"Trip: {booking.itinerary.source_city} to {booking.itinerary.destination_city}", styles["Normal"]),
             Paragraph(f"Booking type: {booking.booking_type}", styles["Normal"]),
             Paragraph(f"Item: {booking.item_name}", styles["Normal"]),
             Paragraph(f"Travelers: {booking.number_of_people}", styles["Normal"]),
             Paragraph(f"Status: {booking.booking_status}", styles["Normal"]), Spacer(1, 16),
             Paragraph(f"Total: {rupee(booking.total_price)}", styles["Heading2"]),
             Paragraph("This receipt covers a simulated booking in the Roamwise demo.", styles["Normal"])]
    document.build(story)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"roamwise-receipt-{booking.id}.pdf", mimetype="application/pdf")


@app.route("/recommendations")
@login_required
def recommendations():
    preference = current_user.preference
    interests = {item.strip().lower() for item in (preference.interests or "").split(",") if item.strip()}
    destinations = Destination.query.all()
    ranked = sorted(destinations, key=lambda item: (
        item.category.lower() in interests,
        -abs(item.average_daily_cost - preference.maximum_budget / 7),
        -item.popularity_score,
    ), reverse=True)
    return render_template("recommendations.html", destinations=ranked[:8], preference=preference)


@app.route("/help", methods=["GET", "POST"])
def help_center():
    if request.method == "POST":
        name = request.form.get("name", current_user.name if current_user.is_authenticated else "").strip()
        email = request.form.get("email", current_user.email if current_user.is_authenticated else "").strip().lower()
        category = request.form.get("category", "Other").strip()[:60]
        subject = request.form.get("subject", "").strip()[:180]
        message = request.form.get("message", "").strip()
        if not name or not email or "@" not in email or not subject or not 10 <= len(message) <= 3000:
            flash("Complete the contact details and describe the issue in at least 10 characters.", "danger")
        else:
            db.session.add(SupportTicket(user_id=current_user.id if current_user.is_authenticated else None, name=name, email=email, category=category or "Other", subject=subject, message=message))
            try:
                for attempt in range(3):
                    try:
                        db.session.commit()
                        break
                    except OperationalError:
                        db.session.rollback()
                        if attempt == 2:
                            raise
                        time.sleep(1)
            except OperationalError:
                db.session.rollback()
                flash("The database is busy. Close DB Browser or other database windows, then submit again.", "warning")
            else:
                flash("Your support request was received. Our customer-care team will review it.", "success")
                return redirect(url_for("help_center"))
    return render_template("help.html")


@app.route("/account/export")
@login_required
def export_account_data():
    data = {
        "profile": {"name": current_user.name, "email": current_user.email, "created_at": current_user.created_at.isoformat()},
        "preferences": {"travel_style": current_user.preference.travel_style, "interests": current_user.preference.interests, "hotel_preference": current_user.preference.hotel_preference, "maximum_budget": current_user.preference.maximum_budget},
        "itineraries": [{"id": trip.id, "source": trip.source_city, "destination": trip.destination_city, "departure": trip.departure_date.isoformat(), "return": trip.return_date.isoformat(), "total_cost": trip.total_cost} for trip in current_user.itineraries],
        "favorites": [item.destination_id for item in FavoriteDestination.query.filter_by(user_id=current_user.id).all()],
        "reviews": [{"destination_id": item.destination_id, "rating": item.rating, "body": item.body} for item in Review.query.filter_by(user_id=current_user.id).all()],
    }
    return send_file(BytesIO(json.dumps(data, indent=2).encode("utf-8")), as_attachment=True, download_name="roamwise-account-export.json", mimetype="application/json")


@app.route("/account/delete", methods=["POST"])
@login_required
def delete_account():
    if not check_password_hash(current_user.password_hash, request.form.get("password", "")):
        flash("Enter your current password to delete the account.", "danger")
        return redirect(url_for("profile"))
    user_id = current_user.id
    for model in (FavoriteDestination, Review, PackingItem, Notification, Booking):
        model.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    ItineraryShare.query.filter(ItineraryShare.itinerary_id.in_(db.session.query(Itinerary.id).filter_by(user_id=user_id))).delete(synchronize_session=False)
    UserPreference.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    Itinerary.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    PasswordReset.query.filter_by(email=current_user.email).delete(synchronize_session=False)
    user = db.session.get(User, user_id)
    db.session.delete(user)
    db.session.commit()
    logout_user()
    flash("Your account and personal data were deleted.", "info")
    return redirect(url_for("home"))


@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    return render_template("admin.html", users=User.query.order_by(User.created_at.desc()).all(), destinations=Destination.query.order_by(Destination.city_name).all(), itineraries=Itinerary.query.order_by(Itinerary.created_at.desc()).limit(20).all(), bookings=Booking.query.order_by(Booking.booking_date.desc()).limit(20).all(), support_tickets=SupportTicket.query.order_by(SupportTicket.created_at.desc()).limit(20).all())


@app.route("/admin/support/<int:ticket_id>/status", methods=["POST"])
@login_required
@admin_required
def admin_update_support_status(ticket_id):
    ticket = db.get_or_404(SupportTicket, ticket_id)
    status = request.form.get("status", "Open")
    if status not in {"Open", "In progress", "Resolved"}:
        flash("Invalid support status.", "danger")
    else:
        ticket.status = status
        db.session.commit()
        flash("Support request updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/destination/<int:destination_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_destination(destination_id):
    destination = db.get_or_404(Destination, destination_id)
    db.session.delete(destination)
    db.session.commit()
    flash("Destination and its catalog data were deleted.", "info")
    return redirect(url_for("admin_dashboard"))


@app.route("/bookings")
@login_required
def bookings():
    if create_departure_reminders(current_user.id):
        db.session.commit()
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    booking_type = request.args.get("type", "").strip()
    query = Booking.query.filter_by(user_id=current_user.id)
    if search:
        term = f"%{search}%"
        query = query.join(Itinerary).filter(or_(
            Booking.booking_reference.ilike(term),
            Booking.item_name.ilike(term),
            Itinerary.source_city.ilike(term),
            Itinerary.destination_city.ilike(term),
        ))
    if status in {"Confirmed", "Cancelled"}:
        query = query.filter_by(booking_status=status)
    if booking_type in {"Transport", "Hotel", "Activity"}:
        query = query.filter_by(booking_type=booking_type)
    booking_list = query.order_by(Booking.booking_date.desc()).all()
    refund_estimates = {booking.id: calculate_refund(booking) for booking in booking_list}
    return render_template("bookings.html", bookings=booking_list, search=search, status=status,
                           booking_type=booking_type, refund_estimates=refund_estimates)


@app.route("/train-booking")
@login_required
def train_booking():
    return render_template("train_booking.html")


@app.route("/booking/<int:booking_id>/cancel", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    if booking.user_id != current_user.id or booking.booking_status == "Cancelled":
        flash("This booking cannot be cancelled.", "warning")
        return redirect(url_for("bookings"))
    refund_amount, refund_status = calculate_refund(booking)
    booking.booking_status = "Cancelled"
    booking.refund_amount = refund_amount
    booking.refund_status = refund_status
    booking.cancelled_at = datetime.utcnow()
    if booking.hotel_id:
        hotel = db.session.get(Hotel, booking.hotel_id)
        if hotel:
            hotel.available_rooms += 1
    create_notification(current_user.id, "Booking cancelled",
                        f"{booking.item_name} was cancelled. Refund: {rupee(refund_amount)} ({refund_status}).", "booking")
    db.session.commit()
    try:
        send_transaction_email(
            current_user.email,
            f"Roamwise booking cancelled · {booking.booking_reference or booking.id}",
            f"Hi {current_user.name},\n\nYour {booking.booking_type.lower()} booking "
            f"({booking.item_name}) has been cancelled.\n"
            f"Reference: {booking.booking_reference or booking.id}\n"
            f"Refund: {rupee(refund_amount)} ({refund_status}).\n\n"
            "This is a simulated refund in the Roamwise demo.",
        )
    except (OSError, smtplib.SMTPException):
        app.logger.warning("Unable to send booking cancellation email", exc_info=True)
    flash(f"Booking cancelled. Refund: {rupee(refund_amount)} ({refund_status}).", "info")
    return redirect(url_for("bookings"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        current_user.name = request.form.get("name", current_user.name).strip()
        phone_number = request.form.get("phone_number", "").strip()
        if phone_number and (len(phone_number) > 30 or not all(character.isdigit() or character in "+-() " for character in phone_number)):
            flash("Enter a valid phone number.", "danger")
            return render_template("profile.html")
        current_user.phone_number = phone_number or None
        db.session.commit()
        flash("Your profile details were saved.", "success")
    return render_template("profile.html")


def upgrade_existing_schema():
    """Add nullable fields to databases created by earlier app versions."""
    columns = {column["name"] for column in inspect(db.engine).get_columns("user")}
    if "phone_number" not in columns:
        db.session.execute(text("ALTER TABLE `user` ADD COLUMN phone_number VARCHAR(30)"))
        db.session.commit()
    booking_columns = {column["name"] for column in inspect(db.engine).get_columns("booking")}
    additions = {
        "booking_reference": "VARCHAR(24)",
        "refund_amount": "FLOAT DEFAULT 0",
        "refund_status": "VARCHAR(30) DEFAULT 'Not requested'",
        "cancelled_at": "DATETIME",
    }
    changed = False
    for name, definition in additions.items():
        if name not in booking_columns:
            db.session.execute(text(f"ALTER TABLE booking ADD COLUMN {name} {definition}"))
            changed = True
    if changed:
        db.session.commit()
    # Backfill references without changing or deleting any existing booking rows.
    for booking in Booking.query.filter(Booking.booking_reference.is_(None)).all():
        booking.booking_reference = f"RW-{booking.id:08d}-{secrets.token_hex(2).upper()}"
    db.session.commit()
    if db.engine.dialect.name == "sqlite":
        db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_reference ON booking (booking_reference)"))
        db.session.commit()


@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


def seed_database():
    if Destination.query.first():
        return
    destination_data = [
        ("Delhi", "Delhi", "India’s energetic capital blends old monuments, food lanes and modern culture.", "October–March", 3600, "City", 94, "https://images.unsplash.com/photo-1587474260584-136574528ed5?auto=format&fit=crop&w=900&q=80"),
        ("Mumbai", "Maharashtra", "A lively coastal metropolis known for art, cinema, markets and the Arabian Sea.", "October–February", 4300, "City", 92, "https://images.unsplash.com/photo-1570168007204-dfb528c6958f?auto=format&fit=crop&w=900&q=80"),
        ("Goa", "Goa", "Relaxed beaches, Portuguese heritage, water sports and memorable sunsets.", "November–February", 3900, "Beach", 96, "https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?auto=format&fit=crop&w=900&q=80"),
        ("Jaipur", "Rajasthan", "The Pink City is filled with royal forts, colorful bazaars and Rajasthani cuisine.", "October–March", 2900, "Historical", 91, "https://images.unsplash.com/photo-1477587458883-47145ed94245?auto=format&fit=crop&w=900&q=80"),
        ("Agra", "Uttar Pradesh", "Home of the Taj Mahal, Mughal architecture and rich heritage.", "October–March", 2600, "Historical", 89, "https://images.unsplash.com/photo-1564507592333-c60657eea523?auto=format&fit=crop&w=900&q=80"),
        ("Manali", "Himachal Pradesh", "A Himalayan escape for mountain views, snow, cafes and adventure.", "October–June", 3200, "Mountain", 90, "https://images.unsplash.com/photo-1626621341517-bbf3d9990a23?auto=format&fit=crop&w=900&q=80"),
        ("Rishikesh", "Uttarakhand", "River rafting, yoga, forest trails and spiritual riverfronts.", "September–June", 2500, "Adventure", 86, "https://images.unsplash.com/photo-1609920658906-8223bd289001?auto=format&fit=crop&w=900&q=80"),
        ("Kochi", "Kerala", "Historic lanes, waterfront promenades and a gateway to Kerala’s backwaters.", "October–March", 3400, "Nature", 84, "https://images.unsplash.com/photo-1593693397690-362cb9666fc2?auto=format&fit=crop&w=900&q=80"),
        ("Udaipur", "Rajasthan", "Romantic lakes, ornate palaces and sunset views in the City of Lakes.", "October–March", 3300, "Historical", 88, "https://images.unsplash.com/photo-1602643163983-ed0babc39797?auto=format&fit=crop&w=900&q=80"),
        ("Varanasi", "Uttar Pradesh", "An ancient river city with ghats, temples and cultural traditions.", "October–March", 2300, "Religious", 85, "https://images.unsplash.com/photo-1561361513-2d000a50f0dc?auto=format&fit=crop&w=900&q=80"),
        ("Darjeeling", "West Bengal", "Tea gardens, mountain railways and Kanchenjunga viewpoints.", "March–May, October–November", 3000, "Mountain", 83, "https://images.unsplash.com/photo-1544634076-a90160b4f6c7?auto=format&fit=crop&w=900&q=80"),
        ("Bengaluru", "Karnataka", "Garden-city parks, food, technology hubs and weekend escapes.", "October–February", 3800, "City", 87, "https://images.unsplash.com/photo-1596176530529-78163a4f7af2?auto=format&fit=crop&w=900&q=80"),
    ]
    destinations = []
    for city, state, description, season, daily, category, popularity, image in destination_data:
        item = Destination(city_name=city, state=state, description=description, best_time_to_visit=season, average_daily_cost=daily, category=category, popularity_score=popularity, image_url=image)
        destinations.append(item)
        db.session.add(item)
    db.session.flush()

    hotel_suffixes = [("Traveller Nest", "Budget", 1450, 3.9), ("Comfort Inn", "Budget", 2200, 4.1), ("Central Suites", "Standard", 4100, 4.3), ("Grand Residency", "Standard", 5600, 4.5), ("Royal Horizon", "Luxury", 10500, 4.8)]
    attraction_templates = {
        "Beach": [("Sunset Beach", "Nature", 0), ("Fort Aguada", "History", 50), ("Water Sports Bay", "Adventure", 1800), ("Seafood Market", "Food", 200), ("Coastal Chapel", "History", 0)],
        "Historical": [("Heritage Palace", "History", 300), ("Old City Bazaar", "Shopping", 0), ("Local Food Walk", "Food", 450), ("Museum Quarter", "History", 150), ("Sunset Viewpoint", "Nature", 0)],
        "Mountain": [("Mountain Viewpoint", "Nature", 0), ("Valley Trek", "Adventure", 600), ("Tea & Cafe Trail", "Food", 250), ("Local Market", "Shopping", 0), ("Hill Temple", "Religious", 50)],
        "Adventure": [("River Rafting", "Adventure", 1500), ("Riverside Ghat", "Religious", 0), ("Forest Trail", "Nature", 100), ("Yoga Centre", "Wellness", 400), ("Café Lane", "Food", 200)],
        "Nature": [("Backwater Cruise", "Nature", 1200), ("Spice Market", "Food", 0), ("Heritage Walk", "History", 150), ("Bird Sanctuary", "Nature", 200), ("Handicraft Centre", "Shopping", 100)],
        "Religious": [("Morning Ghat Ceremony", "Religious", 0), ("Ancient Temple", "Religious", 50), ("Street Food Trail", "Food", 250), ("Silk Market", "Shopping", 0), ("River Boat Ride", "Nature", 300)],
        "City": [("City Heritage Walk", "History", 150), ("Street Food Market", "Food", 250), ("Urban Park", "Nature", 0), ("Art District", "Shopping", 100), ("Night View Deck", "Nightlife", 500)],
    }
    for dest in destinations:
        for suffix, category, price, rating in hotel_suffixes:
            db.session.add(Hotel(destination_id=dest.id, hotel_name=f"{dest.city_name} {suffix}", hotel_category=category, price_per_night=price, rating=rating,
                                 amenities="Wi-Fi, Breakfast, Air conditioning", address=f"Central {dest.city_name}", available_rooms=12))
        for index, (name, category, fee) in enumerate(attraction_templates[dest.category], start=1):
            db.session.add(Attraction(destination_id=dest.id, attraction_name=f"{dest.city_name} {name}", category=category,
                                      description=f"A popular {category.lower()} experience in {dest.city_name}.", entry_fee=fee, estimated_duration_hours=2 + index % 3, rating=3.9 + index / 10))
    cities = [d.city_name for d in destinations]
    for origin_index, origin in enumerate(cities):
        for destination_index, destination in enumerate(cities):
            if origin == destination:
                continue
            distance_factor = 1 + abs(origin_index - destination_index) * 0.14
            data = [
                ("Bus", "InterCity Travels", "06:30", "17:00", round(8 * distance_factor, 1), round(900 * distance_factor), "Sleeper", 3.9),
                ("Train", "Indian Railways", "07:15", "15:30", round(6 * distance_factor, 1), round(1400 * distance_factor), "AC Chair Car", 4.2),
                ("Flight", "SkyConnect", "09:40", "11:20", round(1.6 * distance_factor, 1), round(4800 * distance_factor), "Economy", 4.5),
            ]
            for mode, provider, depart, arrive, duration, price, class_type, rating in data:
                db.session.add(TransportOption(source_city=origin, destination_city=destination, transport_type=mode, provider_name=provider,
                                                departure_time=depart, arrival_time=arrive, duration_hours=duration, price_per_person=price, class_type=class_type, rating=rating))
    db.session.commit()


def initialize_database():
    with app.app_context():
        db.create_all()
        upgrade_existing_schema()
        seed_database()


# Initialize the schema and seed data for both local runs and production servers.
initialize_database()


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        upgrade_existing_schema()
        seed_database()
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)
