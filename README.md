# Roamwise — Travel and Hospitality Planner

A full-stack Flask travel itinerary application. Users can create secure accounts, set travel preferences, compare budget/standard/luxury packages, save itineraries and manage simulated bookings.

## Features

- Signup/login with hashed passwords and protected pages
- Custom SQLite travel dataset: 12 Indian cities, 60 hotels, 60 attractions and 396 transport options
- Smart package comparison covering transport, hotel, activities, meals and local travel
- Budget optimization: package cost is compared to the entered budget and the most affordable in-budget option is recommended
- Day-wise saved itinerary and booking management with simulated cancellation
- Responsive Bootstrap interface built with HTML, CSS and JavaScript

## Technology

Python, Flask, Flask-SQLAlchemy, Flask-Login, SQLite, HTML5, CSS3, Bootstrap 5 and JavaScript.

## Run locally

```powershell
cd D:\project
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000` in a browser.

The application automatically creates and seeds the database when `app.py` is run for the first time. `seed_data.py` is therefore optional, but useful when setting up the application explicitly.

## Email OTP verification

New accounts must verify a six-digit code sent to their email before the account is created. Configure an SMTP provider before running in production:

```powershell
$env:SMTP_HOST="smtp.gmail.com"
$env:SMTP_PORT="587"
$env:SMTP_USERNAME="your-gmail-address@gmail.com"
$env:SMTP_PASSWORD="your-16-character-gmail-app-password"
$env:SMTP_FROM="your-gmail-address@gmail.com"
$env:SECRET_KEY="replace-with-a-long-random-secret"
python app.py
```

The same Gmail delivery is used for signup verification and password reset. OTPs are never rendered in the browser or printed in the server terminal. If SMTP is not configured, the app rejects the request instead of exposing the code.

## Budget logic

The system calculates:

`transport + hotel + activities + food estimate + local transport estimate`

Food allowance per person/day is ₹800 for Budget, ₹1,500 for Standard, and ₹3,000 for Luxury. Local travel is estimated as ₹400 per person/day. All packages are compared to the traveler’s stated trip budget; the lowest-cost in-budget package becomes the default recommendation.

## Production note

This is a demonstration project. Set a strong `SECRET_KEY`, switch to MySQL/PostgreSQL, add CSRF protection, use real inventory/provider APIs, and build proper payment processing before production use.
