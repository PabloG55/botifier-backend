from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# Create the shared SQLAlchemy object (not bound to app yet)
db = SQLAlchemy()
import pytz
ECUADOR_TZ = pytz.timezone("America/Guayaquil")

# User model
class User(db.Model):
    id = db.Column(db.BigInteger, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True)
    firebase_uid = db.Column(db.String(128), unique=True)
    email = db.Column(  db.String(255))
    username = db.Column(db.String(100))
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    photo_url = db.Column(db.String(300))
    joined_at = db.Column(db.DateTime, default=datetime.now(ECUADOR_TZ))
    google_access_token = db.Column(db.String(512))
    google_refresh_token = db.Column(db.String(512))
    google_calendar_integrated = db.Column(db.Boolean, default=False)
    tasks = db.relationship('Task', backref='user', lazy=True)


# Task model
class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('user.id'), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    scheduled_time = db.Column(db.DateTime(timezone=True), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.now(ECUADOR_TZ))
    reminder_sent = db.Column(db.Boolean, default=False)
    followup_sent = db.Column(db.Boolean, default=False)
    current_reminder_type = db.Column(db.String(50), default='initial')
    reminder_sent_at = db.Column(db.DateTime(timezone=True))
    google_calendar_event_id = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f"<Task {self.id} - {self.description} - {self.scheduled_time} - {self.status}>"

class KeyValueStore(db.Model):
    key = db.Column(db.String, primary_key=True)
    value = db.Column(db.Text)


