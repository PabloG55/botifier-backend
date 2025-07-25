# backend/helpers/google_calendar.py

import os
from datetime import timedelta
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import logging


from helpers.config import (
    GOOGLE_WEB_CLIENT_SECRETS_FILE,
    GOOGLE_WEB_CLIENT_ID,
    GOOGLE_WEB_CLIENT_SECRET,
)

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/calendar']
REDIRECT_URI = f"{os.environ.get('BASE_URL')}/api/google/callback"


def get_google_auth_flow():
    """Initializes the OAuth flow using the specific web client secrets file."""
    return Flow.from_client_secrets_file(
        GOOGLE_WEB_CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )


def _get_credentials_from_user(user):
    """Helper function to build a refreshable Credentials object from a user model."""
    if not user.google_calendar_integrated:
        return None


    return Credentials(
        token=user.google_access_token,
        refresh_token=user.google_refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=GOOGLE_WEB_CLIENT_ID,
        client_secret=GOOGLE_WEB_CLIENT_SECRET,
        scopes=SCOPES
    )


def create_event(user, task):
    """Creates a new event on the user's primary calendar."""
    creds = _get_credentials_from_user(user)
    if not creds:
        return None

    try:
        service = build('calendar', 'v3', credentials=creds)
        event_body = {
            'summary': task.description,
            'start': {'dateTime': task.scheduled_time.isoformat(), 'timeZone': 'America/Guayaquil'},
            'end': {'dateTime': (task.scheduled_time + timedelta(hours=1)).isoformat(),
                    'timeZone': 'America/Guayaquil'},
        }
        created_event = service.events().insert(calendarId='primary', body=event_body).execute()
        logger.info(f"✅ Google Calendar event created: {created_event.get('id')}")
        return created_event.get('id')
    except HttpError as error:
        logger.error(f"❌ An error occurred creating Google Calendar event: {error}")
        return None


def update_event(user, task):
    """Updates an existing Google Calendar event."""
    if not task.google_calendar_event_id:
        return

    creds = _get_credentials_from_user(user)
    if not creds:
        return

    try:
        service = build('calendar', 'v3', credentials=creds)
        event_body = {
            'summary': task.description,
            'start': {'dateTime': task.scheduled_time.isoformat(), 'timeZone': 'America/Guayaquil'},
            'end': {'dateTime': (task.scheduled_time + timedelta(hours=1)).isoformat(),
                    'timeZone': 'America/Guayaquil'},
        }
        service.events().update(calendarId='primary', eventId=task.google_calendar_event_id, body=event_body).execute()
        logger.info(f"✅ Google Calendar event updated: {task.google_calendar_event_id}")
    except HttpError as error:
        logger.error(f"❌ An error occurred updating Google Calendar event: {error}")


def delete_event(user, task):
    """Deletes an event from the user's Google Calendar."""
    if not task.google_calendar_event_id:
        return

    creds = _get_credentials_from_user(user)
    if not creds:
        return

    try:
        service = build('calendar', 'v3', credentials=creds)
        service.events().delete(calendarId='primary', eventId=task.google_calendar_event_id).execute()
        logger.info(f"✅ Google Calendar event deleted: {task.google_calendar_event_id}")
    except HttpError as error:
        # If the event is already deleted (404), we can ignore the error.
        if error.resp.status == 404:
            logger.warning(
                f"⚠️ Google Calendar event not found (perhaps already deleted): {task.google_calendar_event_id}")
        else:
            logger.error(f"❌ An error occurred deleting Google Calendar event: {error}")