from datetime import datetime, timedelta
import logger
from dateutil.parser import isoparse
from flask_cors import CORS

from helpers.internship_sender import send_internship_alert
from helpers.reminder_sender import send_reminder
from helpers.config import *
from flask import Flask, request, jsonify, Blueprint, redirect, session
import os
import requests
import uuid
import logging
from helpers.job_utils import remove_jobs_for_task, schedule_jobs_for_task
from helpers.reminder_parser import process_text_command
from helpers.transcriber import transcribe_audio
from helpers.db import db, Task, User
import pytz
from helpers.google_calendar import get_google_auth_flow, create_event, update_event, delete_event

ECUADOR_TZ = pytz.timezone("America/Guayaquil")

# Configure logging only once
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%d/%b/%Y %H:%M:%S'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)
reminders_bp = Blueprint('reminders', __name__)
CORS(app, supports_credentials=True)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 280,
    "connect_args": {"sslmode": "require"},
}

db.init_app(app)

with app.app_context():
    db.create_all()

# Configure constants
MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB
ALLOWED_AUDIO_TYPES = {'audio/wav', 'audio/mp3', 'audio/ogg'}
DOWNLOAD_TIMEOUT = 30  # seconds
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

@app.route("/api/firebase-login", methods=["POST"])
def firebase_login():
    data = request.get_json()
    firebase_uid = data.get("uid")
    email = data.get("email")

    if not firebase_uid or not email:
        return jsonify({"error": "Missing uid or email"}), 400

    user = User.query.filter_by(firebase_uid=firebase_uid).first()
    if not user:
        user = User(firebase_uid=firebase_uid, email=email)
        db.session.add(user)
        db.session.commit()

    return jsonify({ "ok": True })

@app.route("/api/user-status", methods=["GET"])
def get_user_status():
    firebase_uid = request.args.get("uid")
    if not firebase_uid:
        return jsonify({"error": "Missing uid"}), 400

    user = User.query.filter_by(firebase_uid=firebase_uid).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "telegram_connected": user.telegram_id is not None,
        "email": user.email
    })

@app.route("/bot", methods=["POST"])
def bot():
    data = request.get_json()
    logger.info("📥 Incoming Telegram payload:")
    logger.info(data)

    try:
        message = data.get("message", {})
        text = message.get("text", "").strip()
        chat_id = message.get("chat", {}).get("id")

        if not chat_id:
            return jsonify({"ok": True})  # Ignore if no chat

        # Handle voice messages
        if "voice" in message:
            file_id = message["voice"]["file_id"]

            # Step 1: Get a file path from Telegram
            file_info = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
            file_path = file_info["result"]["file_path"]
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"

            # Download the voice file
            r = requests.get(file_url, timeout=DOWNLOAD_TIMEOUT)
            r.raise_for_status()

            # Check file size
            if len(r.content) > MAX_CONTENT_LENGTH:
                reply = "❌ Sorry, the audio file is too large. Please send a shorter message."
            else:
                # Save the file
                filename = f"temp_{uuid.uuid4()}.ogg"
                with open(filename, "wb") as f:
                    f.write(r.content)

                try:
                    # Transcribe and process
                    transcription = transcribe_audio(filename)
                    result = process_text_command(transcription, telegram_id=chat_id)
                    reply = result or f"❌ I couldn't understand: \"{transcription}\""
                except Exception as e:
                    logger.error(f"❌ Error processing audio: {str(e)}")
                    reply = "❌ Sorry, I couldn't process your voice message."
                finally:
                    if os.path.exists(filename):
                        os.remove(filename)

        else:

            text = message.get("text", "").strip()
            logger.info(f"📨 Text received: '{text}'")

            # Handle start
            if text == "/start":
                reply = "Please paste the /connect unique_code"
                requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": reply
                })
                return jsonify({"ok": True})

            # Handle connect
            if text.lower().startswith("/connect"):
                parts = text.split(" ", 1)
                if len(parts) == 2:
                    firebase_uid = parts[1].strip()
                    user = User.query.filter_by(firebase_uid=firebase_uid).first()
                    if user:
                        user.telegram_id = int(chat_id)
                        db.session.commit()
                        logger.info(f"✅ Linked Telegram ID {chat_id} to user {user.email} (UID: {firebase_uid})")
                        reply = (
                            "✅ Telegram account successfully connected!\n\n"
                            f"You can now return to the app:\nhttps://whatsapp-reminder-frontend.vercel.app/welcome?tg_id={chat_id}"
                        )
                    else:
                        reply = "❌ No user found for this code. Make sure you're logged in."
                else:
                    reply = "❌ Invalid connect code format. Try again."

                requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": reply
                })
                return jsonify({"ok": True})

            # Handle text messages
            result = process_text_command(text, telegram_id=chat_id)
            reply = result or f"❌ I couldn't understand: \"{text}\""

        # Send reply to user
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": reply
        })

    except Exception as e:
        logger.error(f"❌ Unexpected error in /bot: {str(e)}")
        # Try to send a fallback error
        if "chat_id" in locals():
            requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={
                "chat_id": chat_id,
                "text": "❌ An unexpected error occurred."
            })

    return jsonify({"ok": True})

@reminders_bp.route("/run-reminders")
def run_reminders():
    now = datetime.now(ECUADOR_TZ)
    sent_count = 0

    # Initial reminders
    tasks = Task.query.filter(
        Task.scheduled_time <= now,
        Task.status == "pending",
        Task.reminder_sent == False
    ).all()

    for task in tasks:
        try:
            send_reminder(task)
            task.reminder_sent = True
            task.reminder_sent_at = now
            db.session.commit()
            sent_count += 1
        except Exception as e:
            logger.error(f"❌ Error sending reminder for task {task.id}: {e}")

    # Follow-ups (1h after original reminder)
    followup_tasks = Task.query.filter(
        Task.status == "pending",
        Task.reminder_sent == True,
        Task.reminder_sent_at <= now - timedelta(hours=1)
    ).all()

    for task in followup_tasks:
        try:
            send_reminder(task, followup=True)
            task.followup_sent = True
            task.reminder_sent_at = now
            db.session.commit()
            sent_count += 1
        except Exception as e:
            logger.error(f"❌ Error sending follow-up for task {task.id}: {e}")

    return f"✅ Checked reminders at {now.strftime('%H:%M:%S')}. Sent: {sent_count}"


app.register_blueprint(reminders_bp)


@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    firebase_uid = request.args.get("user_id")  # this is uid from frontend

    if not firebase_uid:
        return jsonify({"error": "Missing user_id"}), 400

    user = User.query.filter_by(firebase_uid=firebase_uid).first()
    if not user:
        return jsonify([])

    tasks = Task.query.filter_by(user_id=user.id).order_by(Task.scheduled_time.asc()).all()

    return jsonify([{
        "id": task.id,
        "description": task.description,
        "scheduled_time": task.scheduled_time.astimezone(ECUADOR_TZ).isoformat(),
        "status": task.status
    } for task in tasks])


@app.route("/api/tasks/create", methods=["POST"])
def api_create_task():
    data = request.get_json()
    description = data.get("description")
    scheduled_time = isoparse(data.get("scheduled_time"))

    # Convert from UTC to Ecuador time
    scheduled_time = scheduled_time.astimezone(ECUADOR_TZ)

    firebase_uid = data.get("user_id")
    if not firebase_uid:
        return jsonify({"error": "Missing user_id (firebase_uid)"}), 400

    user = User.query.filter_by(firebase_uid=firebase_uid).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    if user:
        new_task = Task(
            description=description,
            scheduled_time=scheduled_time,
            user_id=user.id
        )
        db.session.add(new_task)
        db.session.commit()

        if user.google_calendar_integrated:
            event_id = create_event(user, new_task)
            if event_id:
                new_task.google_calendar_event_id = event_id
                db.session.commit()

        schedule_jobs_for_task(new_task)
        return jsonify({"message": "Task created", "id": new_task.id}), 201
    return jsonify({"error": "User not found"}), 404


@app.route("/api/tasks/<int:task_id>/complete", methods=["POST"])
def api_complete_task(task_id):
    firebase_uid = request.json.get("user_id")
    task = Task.query.get_or_404(task_id)

    user = User.query.filter_by(firebase_uid=firebase_uid).first()
    if not user or task.user_id != user.id:
        return jsonify({"error": "Unauthorized access"}), 403

    if user and task.user_id == user.id:
        if user.google_calendar_integrated:
            delete_event(user, task)

        remove_jobs_for_task(task.id)
        task.status = "done"
        db.session.commit()
        return jsonify({"message": f"Task {task.id} marked as done."})
    return jsonify({"error": "Unauthorized access"}), 403

@app.route("/api/tasks/<int:task_id>/reschedule", methods=["POST"])
def api_reschedule_task(task_id):
    firebase_uid = request.json.get("user_id")
    task = Task.query.get_or_404(task_id)

    user = User.query.filter_by(firebase_uid=firebase_uid).first()
    if not user or task.user_id != user.id:
        return jsonify({"error": "Unauthorized access"}), 403

    # Reset status to pending if it was done
    if task.status == "done":
        task.status = "pending"

    # Remove old jobs and schedule new ones
    remove_jobs_for_task(task.id)
    schedule_jobs_for_task(task)

    # Re-create the calendar event if it was deleted, or update if it exists
    if user.google_calendar_integrated:
        if task.google_calendar_event_id:
            try:
                # Try to update first
                update_event(user, task)
            except Exception:
                # If update fails (e.g., event deleted), create a new one
                event_id = create_event(user, task)
                task.google_calendar_event_id = event_id
        else:
            event_id = create_event(user, task)
            task.google_calendar_event_id = event_id

    db.session.commit()

    return jsonify({
        "message": f"Task {task.id} rescheduled",
        "task_id": task.id,
        "scheduled_time": task.scheduled_time.isoformat()
    })

@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def api_delete_task(task_id):
    firebase_uid = request.args.get("user_id")
    task = Task.query.get_or_404(task_id)

    user = User.query.filter_by(firebase_uid=firebase_uid).first()
    if not user or task.user_id != user.id:
        return jsonify({"error": "Unauthorized access"}), 403

    if user and task.user_id == user.id:
        if user.google_calendar_integrated:
            delete_event(user, task)

        remove_jobs_for_task(task.id)
        db.session.delete(task)
        db.session.commit()
        return jsonify({"message": f"Task {task.id} deleted."})
    return jsonify({"error": "Unauthorized access"}), 403



@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
def api_edit_task(task_id):
    data = request.get_json()
    firebase_uid = data.get("user_id")
    task = Task.query.get_or_404(task_id)

    user = User.query.filter_by(firebase_uid=firebase_uid).first()
    if not user or task.user_id != user.id:
        return jsonify({"error": "Unauthorized access"}), 403

    task.description = data.get("description", task.description)
    parsed_time = isoparse(data.get("scheduled_time"))

    if parsed_time.tzinfo is None:
        parsed_time = ECUADOR_TZ.localize(parsed_time)
    else:
        parsed_time = parsed_time.astimezone(ECUADOR_TZ)

    task.scheduled_time = parsed_time


    if task.status == "done":
        task.status = "pending"

    if user and task.user_id == user.id:
        remove_jobs_for_task(task.id)
        db.session.commit()
        if user.google_calendar_integrated:
            update_event(user, task)
        schedule_jobs_for_task(task)
        return jsonify({"message": f"Task {task.id} updated."})
    return jsonify({"error": "Unauthorized access"}), 403


@app.route('/api/google/connect')
def google_connect():
    """
    Initiates the Google OAuth flow.
    It expects a 'uid' query parameter from the frontend to identify the user.
    """
    firebase_uid = request.args.get('uid')
    if not firebase_uid:
        return "Error: Missing user identifier (uid). Please include it as a query parameter.", 400

    # Store the user's Firebase UID in the session. It will be retrieved in the callback.
    session['firebase_uid'] = firebase_uid

    flow = get_google_auth_flow()
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        include_granted_scopes='true'
    )
    session['state'] = state
    return redirect(authorization_url)


@app.route('/api/google/callback')
def google_callback():
    """
    Handles the callback from Google after the user grants permission.
    """
    flow = get_google_auth_flow()
    try:
        flow.fetch_token(authorization_response=request.url)
    except Exception as e:
        logger.error(f"Error fetching Google token: {e}")
        return "Error: Could not fetch authentication token from Google.", 400

    credentials = flow.credentials

    # Retrieve the Firebase UID we stored in the session before the redirect.
    firebase_uid = session.get('firebase_uid')
    if not firebase_uid:
        return "Error: User session not found or has expired. Please try connecting again.", 400

    user = User.query.filter_by(firebase_uid=firebase_uid).first()

    if user:
        user.google_access_token = credentials.token
        user.google_refresh_token = credentials.refresh_token
        user.google_calendar_integrated = True
        db.session.commit()

        # Redirect the user back to the frontend dashboard.
        return redirect(f"https://whatsapp-reminder-frontend.vercel.app/dashboard?connected=true")

    return "Error: User not found in our database.", 404

@app.route("/api/github-internship-update", methods=["POST"])
def internship_update():
    data = request.get_json()
    if data.get("token") != "internship2026":
        return jsonify({"error": "unauthorized"}), 403
    send_internship_alert()
    return jsonify({"ok": True})

@app.route("/jobs")
def jobs():
    from helpers.scheduler import scheduler
    jobs = scheduler.get_jobs()
    job_list = [{
        "id": job.id,
        "name": job.name,
        "next_run_time": job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job.next_run_time else None
    } for job in jobs]

    return jsonify(job_list)

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(port=5000, debug=False)
