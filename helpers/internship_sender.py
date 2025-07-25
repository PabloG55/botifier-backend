import os
import json
import re
import hashlib
import requests
import logging
# REMOVED: from flask import current_app as app
from helpers.db import User, KeyValueStore, db
from helpers.config import TELEGRAM_BOT_TOKEN

logger = logging.getLogger(__name__)

# Corrected raw URL for the README file (without '/blob/')
INTERNSHIP_LIST_URL = "https://raw.githubusercontent.com/PabloG55/Summer2026-Internships/dev/README.md"


def compute_hash(internship):
    """Computes a unique hash for an internship to avoid duplicate notifications."""
    data = f"{internship.get('company')}|{internship.get('role')}|{internship.get('url')}|{internship.get('date')}"
    return hashlib.sha256(data.encode()).hexdigest()


def parse_internships():
    """
    Fetches the README from GitHub, parses the markdown table, and returns a list of all internships.
    This version correctly handles sub-roles, extracts status flags (emojis), and cleans HTML from fields.
    """
    try:
        response = requests.get(INTERNSHIP_LIST_URL)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Failed to fetch internship list: {e}")
        return []

    lines = response.text.splitlines()
    table_started = False
    internships = []
    last_company = ""  # Used to remember the company for sub-roles (lines with ↳)

    for line in lines:
        if "| Company | Role | Location" in line:
            table_started = True
            continue

        if not table_started or not line.strip().startswith("|"):
            continue

        # --- FIX: Ignore the markdown table separator line ---
        if '---' in line:
            continue

        parts = [p.strip() for p in line.strip().split("|")[1:-1]]
        if len(parts) < 5:
            continue

        company_raw, role_raw, location_raw, link_raw, date = parts[:5]

        # Handle company name and sub-roles
        company = last_company if '↳' in company_raw else company_raw
        last_company = company if '↳' not in company_raw else last_company

        # Extract flags (emojis) from the role and clean the role name
        flags = re.findall(r'[🛂🇺🇸🔒]', role_raw)
        role = re.sub(r'[🛂🇺🇸🔒]', '', role_raw).strip()

        # Clean HTML tags and line breaks from the location field
        location = re.sub(r'<.*?>', '', location_raw).replace('</br>', ', ')

        # Extract the application URL from the HTML anchor tag
        url_match = re.search(r'href="(.*?)"', link_raw)
        apply_link = url_match.group(1) if url_match else "https://github.com/vanshb03/Summer2026-Internships"

        internships.append({
            "company": company,
            "role": role,
            "location": location,
            "url": apply_link,
            "date": date,
            "flags": flags  # Store the extracted flags
        })

    logger.info(f"✅ Parsed {len(internships)} internships from the list.")
    return internships


def load_last_sent_hash():
    """Loads the hash of the last successfully sent internship from the database."""
    record = KeyValueStore.query.get("last_internship_hash")
    return record.value if record else None


def save_last_sent_hash(internship_hash):
    """Saves the hash of the most recent internship sent to the database."""
    record = KeyValueStore.query.get("last_internship_hash") or KeyValueStore(key="last_internship_hash")
    record.value = internship_hash
    db.session.add(record)
    db.session.commit()


# MODIFIED: The function now accepts the 'app' object as an argument
def send_internship_alert(app):
    """
    Main function to check for new internships and send Telegram alerts for each one, including a legend.
    """
    logger.info("📤 Checking for new internships...")
    try:
        with app.app_context():
            all_internships = parse_internships()
            if not all_internships:
                return

            last_hash = load_last_sent_hash()
            new_internships = []

            if last_hash is None:
                # First run or reset: only process the single most recent internship to avoid spam
                logger.info("First run detected. Processing only the most recent internship.")
                new_internships = [all_internships[0]]
            else:
                # Normal run: find all internships newer than the last one sent
                for internship in all_internships:
                    current_hash = compute_hash(internship)
                    if current_hash == last_hash:
                        break
                    new_internships.append(internship)

            if not new_internships:
                logger.info("⏩ No new internships to send.")
                return

            users = User.query.filter(User.telegram_id.isnot(None)).all()
            if not users:
                logger.warning("⚠️ No users with a telegram_id found to notify.")
                save_last_sent_hash(compute_hash(new_internships[0]))
                return

            # Reverse the list to send the oldest new internship first
            for internship in reversed(new_internships):
                flags_str = " ".join(internship.get('flags', []))
                notes_line = f"ℹ️ *Notes:* {flags_str}\n" if flags_str else ""

                message = (
                    f"📢 *New Internship Alert!*\n\n"
                    f"🏢 *Company:* {internship['company']}\n"
                    f"💼 *Role:* {internship['role']}\n"
                    f"📍 *Location:* {internship['location']}\n"
                    f"📅 *Posted:* {internship['date']}\n"
                    f"{notes_line}\n"
                    f"🔗 [Apply Here]({internship['url']})"
                )

                if flags_str:
                    legend = (
                        "\n\n--------------------\n"
                        "*Legend:*\n"
                        "🛂 - No Sponsorship\n"
                        "🇺🇸 - US Citizenship Required\n"
                        "🔒 - Application Closed"
                    )
                    message += legend

                for user in users:
                    payload = {
                        "chat_id": user.telegram_id,
                        "text": message,
                        "parse_mode": "Markdown"
                    }
                    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                    response = requests.post(url, json=payload, timeout=10)

                    if response.ok:
                        logger.info(f"✅ Sent alert for {internship['company']} to user {user.id}")
                    else:
                        logger.error(f"❌ Failed to send to {user.id}: {response.text}")

            # After sending all notifications, save the hash of the most recent internship
            latest_hash = compute_hash(new_internships[0])
            save_last_sent_hash(latest_hash)
            logger.info(f"💾 Saved latest hash: {latest_hash}")

    except Exception as e:
        logger.error(f"❌ An unexpected error occurred in background thread: {e}", exc_info=True)
        # We don't re-raise here because it's in a background thread