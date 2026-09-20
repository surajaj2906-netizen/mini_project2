from app import app, db, seed_database

with app.app_context():
    db.create_all()
    seed_database()
    print("Travel dataset is ready in instance/travel.db")
