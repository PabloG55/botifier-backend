import requests
import logging
from flask import current_app as app
import helpers.state as state
from helpers.db import Task
from helpers.config import TELEGRAM_BOT_TOKEN, TELEGRAM_USER_ID

logger = logging.getLogger(__name__)

def send_reminder(task, followup=False):
    logger.info(f"📤 Sending {'follow-up' if followup else 'initial'} reminder for task: {task.description}")

    try:
        with app.app_context():
            # Get the user's telegram_id
            from helpers.db import User
            user = User.query.get(task.user_id)
            if not user or not user.telegram_id:
                logger.error(f"❌ No telegram_id found for user {task.user_id}")
                return

            if followup:
                state.last_follow_up_task_ids[task.user_id] = task.id
                logger.info(f"🔁 Set last_follow_up_task_ids[{task.user_id}] = {task.id} for '{task.description}'")

        # Prepare message
        if followup:
            message_body = f"✅ Did you finish: '{task.description}'? Reply YES or NO"
        else:
            message_body = f"🔔 Reminder: '{task.description}'"

        # Send message via Telegram
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": user.telegram_id,  # Use telegram_id, not user_id
            "text": message_body
        }
        response = requests.post(url, json=payload)

        if response.ok:
            logger.info("✅ Message sent successfully via Telegram")
        else:
            logger.error(f"❌ Failed to send Telegram message: {response.text}")

    except Exception as e:
        logger.error(f"❌ Error sending Telegram reminder for task {task.id}: {str(e)}")
        raise