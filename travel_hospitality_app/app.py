import os
from datetime import date, datetime
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-before-production")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///travel.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
os.makedirs(app.instance_path, exist_ok=True)
db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
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


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def rupee(value):
    return f"₹{value:,.0f}"


app.jinja_env.filters["rupee"] = rupee


def destination_by_city(city):
    return Destination.query.filter_by(city_name=city).first()


def trip_options(source, destination, depart, returning, travelers, budget, style, interests, hotel_pref):
    """Compare three packages; the lowest-cost in-budget package is the budget recommendation."""
    dest = destination_by_city(destination)
    transport = TransportOption.query.filter_by(source_city=source, destination_city=destination).all()
    hotels = Hotel.query.filter_by(destination_id=dest.id).filter(Hotel.available_rooms > 0).all() if dest else []
    attractions = Attraction.query.filter_by(destination_id=dest.id).all() if dest else []
    if not transport or not hotels:
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
            user = User(name=name, email=email, password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.flush()
            db.session.add(UserPreference(user_id=user.id))
            db.session.commit()
            login_user(user)
            flash("Account created. Start planning your first journey!", "success")
            return redirect(url_for("dashboard"))
    return render_template("signup.html")


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


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    itineraries = Itinerary.query.filter_by(user_id=current_user.id).order_by(Itinerary.created_at.desc()).limit(4).all()
    destinations = Destination.query.order_by(Destination.popularity_score.desc()).limit(4).all()
    return render_template("dashboard.html", itineraries=itineraries, destinations=destinations)


@app.route("/destinations")
def destinations():
    category = request.args.get("category", "")
    query = Destination.query
    if category:
        query = query.filter_by(category=category)
    return render_template("destinations.html", destinations=query.order_by(Destination.popularity_score.desc()).all(), category=category)


@app.route("/destinations/<int:destination_id>")
def destination_detail(destination_id):
    dest = db.get_or_404(Destination, destination_id)
    return render_template("destination_detail.html", destination=dest)


@app.route("/planner", methods=["GET", "POST"])
@login_required
def planner():
    cities = [d.city_name for d in Destination.query.order_by(Destination.city_name).all()]
    if request.method == "POST":
        source, destination = request.form.get("source"), request.form.get("destination")
        try:
            departure = datetime.strptime(request.form.get("departure_date"), "%Y-%m-%d").date()
            returning = datetime.strptime(request.form.get("return_date"), "%Y-%m-%d").date()
            travelers = int(request.form.get("travelers", 1))
            budget = float(request.form.get("budget", 0))
        except (TypeError, ValueError):
            flash("Enter valid travel dates, traveler count, and budget.", "danger")
            return render_template("planner.html", cities=cities, preference=current_user.preference, today=date.today().isoformat())
        interests = request.form.getlist("interests")
        if source == destination or departure < date.today() or returning <= departure or travelers < 1 or budget <= 0:
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
        db.session.add(Booking(user_id=current_user.id, itinerary_id=itinerary.id, booking_type=booking_type, item_name=item_name, hotel_id=hotel_id, number_of_people=trip["travelers"], total_price=amount))
    p["hotel"].available_rooms -= 1
    db.session.commit()
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
    return render_template("itinerary_detail.html", itinerary=itinerary)


@app.route("/bookings")
@login_required
def bookings():
    booking_list = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.booking_date.desc()).all()
    return render_template("bookings.html", bookings=booking_list)


@app.route("/booking/<int:booking_id>/cancel", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    if booking.user_id != current_user.id or booking.booking_status == "Cancelled":
        flash("This booking cannot be cancelled.", "warning")
        return redirect(url_for("bookings"))
    booking.booking_status = "Cancelled"
    if booking.hotel_id:
        hotel = db.session.get(Hotel, booking.hotel_id)
        if hotel:
            hotel.available_rooms += 1
    db.session.commit()
    flash("Booking cancelled. This is a simulated cancellation.", "info")
    return redirect(url_for("bookings"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    pref = current_user.preference
    if request.method == "POST":
        current_user.name = request.form.get("name", current_user.name).strip()
        pref.travel_style = request.form.get("travel_style", "Budget")
        pref.hotel_preference = request.form.get("hotel_preference", "Budget")
        pref.interests = ",".join(request.form.getlist("interests"))
        try:
            pref.maximum_budget = float(request.form.get("maximum_budget", pref.maximum_budget))
        except ValueError:
            flash("Budget must be a number.", "danger")
            return render_template("profile.html", preference=pref)
        db.session.commit()
        flash("Your travel preferences were saved.", "success")
    return render_template("profile.html", preference=pref)


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


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed_database()
    app.run(host="0.0.0.0", port=5000, debug=True)
