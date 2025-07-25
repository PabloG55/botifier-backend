from app import app
from helpers.db import db

with app.app_context():
    db.create_all()
    print("✅ Database initialized.")
