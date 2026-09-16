import json
import os
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class GoogleMeetConfigurationError(RuntimeError):
    """Raised when Google Meet cannot be configured or a meeting cannot be created."""


class GoogleMeetProvider:
    scopes = ["https://www.googleapis.com/auth/calendar"]

    def __init__(self):
        raw_credentials = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not raw_credentials:
            raise GoogleMeetConfigurationError("GOOGLE_SERVICE_ACCOUNT_JSON is not configured.")
        try:
            credentials_info = json.loads(raw_credentials)
            credentials = service_account.Credentials.from_service_account_info(credentials_info, scopes=self.scopes)
            delegated_user = os.getenv("GOOGLE_WORKSPACE_DELEGATED_USER")
            if delegated_user:
                credentials = credentials.with_subject(delegated_user)
            self.calendar = build("calendar", "v3", credentials=credentials, cache_discovery=False)
            self.calendar_id = os.getenv("GOOGLE_MEET_CALENDAR_ID", "primary")
        except (ValueError, TypeError, KeyError) as error:
            raise GoogleMeetConfigurationError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON credentials.") from error

    def create_meeting(self, *, title: str, start_at: datetime, end_at: datetime, description: str) -> str:
        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_at.isoformat(), "timeZone": "Asia/Kolkata"},
            "end": {"dateTime": end_at.isoformat(), "timeZone": "Asia/Kolkata"},
            "conferenceData": {
                "createRequest": {
                    "requestId": f"aiml-{int(start_at.timestamp())}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }
        try:
            created = self.calendar.events().insert(
                calendarId=self.calendar_id,
                body=event,
                conferenceDataVersion=1,
                sendUpdates="all",
            ).execute()
        except HttpError as error:
            raise GoogleMeetConfigurationError("Google Calendar could not create the Meet event.") from error
        entry_points = (created.get("conferenceData") or {}).get("entryPoints") or []
        for entry_point in entry_points:
            if entry_point.get("entryPointType") == "video" and entry_point.get("uri"):
                return entry_point["uri"]
        raise GoogleMeetConfigurationError("Google Calendar created no usable Meet link.")
