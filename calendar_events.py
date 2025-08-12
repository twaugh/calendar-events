#!/usr/bin/env python3
"""
Google Calendar Events Fetcher

Fetches Google Calendar events and outputs them in JSON format.
Filters out workingLocation events and applies attendee-based filtering.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

def get_credentials() -> Credentials:
    """Get Google Calendar API credentials using OAuth2."""
    creds = None
    token_path = Path.home() / '.google' / 'token.json'
    credentials_path = Path.home() / '.google' / 'credentials.json'

    # The file token.json stores the user's access and refresh tokens.
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_path.exists():
                print(f"Error: Credentials file not found at {credentials_path}")
                print("Please ensure you have a valid credentials.json file from Google Cloud Console.")
                sys.exit(1)

            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the credentials for the next run
        token_path.parent.mkdir(exist_ok=True)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    return creds

def get_user_email(service) -> str:
    """Extract user email from the authenticated service."""
    try:
        # Get the primary calendar which contains the user's email
        calendar = service.calendars().get(calendarId='primary').execute()
        return calendar.get('id', '')
    except HttpError as error:
        print(f"An error occurred while getting user email: {error}")
        # Fallback: try to infer from system username
        import getpass
        username = getpass.getuser()
        return f"{username}@redhat.com"

def parse_human_date(date_str: str) -> datetime:
    """
    Parse human-readable date strings like '2 weeks ago', 'tomorrow', 'next Monday', etc.
    Also supports standard formats like '2024-01-15'.
    """
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    date_str = date_str.strip().lower()

    # Handle relative phrases
    if 'ago' in date_str:
        # Parse phrases like "2 weeks ago", "3 days ago"
        parts = date_str.replace('ago', '').strip().split()
        if len(parts) >= 2:
            try:
                amount = int(parts[0])
                unit = parts[1].rstrip('s')  # Remove plural 's'

                if unit in ['day', 'days']:
                    return today - timedelta(days=amount)
                elif unit in ['week', 'weeks']:
                    return today - timedelta(weeks=amount)
                elif unit in ['month', 'months']:
                    return today - relativedelta(months=amount)
                elif unit in ['year', 'years']:
                    return today - relativedelta(years=amount)
            except ValueError:
                pass

    # Handle "in X days/weeks" phrases
    if date_str.startswith('in '):
        parts = date_str[3:].split()
        if len(parts) >= 2:
            try:
                amount = int(parts[0])
                unit = parts[1].rstrip('s')

                if unit in ['day', 'days']:
                    return today + timedelta(days=amount)
                elif unit in ['week', 'weeks']:
                    return today + timedelta(weeks=amount)
                elif unit in ['month', 'months']:
                    return today + relativedelta(months=amount)
                elif unit in ['year', 'years']:
                    return today + relativedelta(years=amount)
            except ValueError:
                pass

    # Handle simple relative terms
    if date_str == 'today':
        return today
    elif date_str == 'yesterday':
        return today - timedelta(days=1)
    elif date_str == 'tomorrow':
        return today + timedelta(days=1)

    # Try to parse with dateutil (handles many formats including "next Monday", "last Friday", etc.)
    try:
        parsed_date = date_parser.parse(date_str, default=today)
        return parsed_date.replace(hour=0, minute=0, second=0, microsecond=0)
    except (ValueError, TypeError):
        pass

    # Fallback: try standard YYYY-MM-DD format
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        raise ValueError(f"Could not parse date: '{date_str}'. Try formats like '2024-01-15', 'yesterday', '2 weeks ago', 'next Monday', etc.")

def parse_date_arguments(start_date: Optional[str], end_date: Optional[str]) -> tuple[datetime, datetime]:
    """
    Parse and validate date arguments according to the specified logic:
    - No dates: Today → Today + 2 weeks
    - Future start date: Start date → Start date + 2 weeks
    - Past start date: Start date → Today (inclusive)
    - End date provided: Use the explicit range
    """
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Parse start date if provided
    if start_date:
        start_dt = parse_human_date(start_date)
    else:
        start_dt = today

    # Parse end date if provided
    if end_date:
        end_dt = parse_human_date(end_date)
        end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    else:
        # Apply the logic based on start date
        if start_dt >= today:
            # Future start date: Start date → Start date + 2 weeks
            end_dt = start_dt + timedelta(days=14)
            end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        else:
            # Past start date: Start date → Today (inclusive)
            end_dt = today.replace(hour=23, minute=59, second=59, microsecond=999999)

    return start_dt, end_dt

def is_user_invited(event: Dict[str, Any], user_email: str) -> bool:
    """Check if the user is invited to the event."""
    attendees = event.get('attendees', [])
    if not attendees:
        return True  # If no attendees list, include the event

    for attendee in attendees:
        if attendee.get('email', '').lower() == user_email.lower():
            return True

    return False

def has_user_declined(event: Dict[str, Any], user_email: str) -> bool:
    """Check if the user has declined the event."""
    attendees = event.get('attendees', [])
    if not attendees:
        return False  # If no attendees list, user hasn't declined

    for attendee in attendees:
        if attendee.get('email', '').lower() == user_email.lower():
            return attendee.get('responseStatus') == 'declined'

    return False

def get_accepted_attendees(event: Dict[str, Any]) -> List[str]:
    """Get list of attendees who have accepted the event."""
    attendees = event.get('attendees', [])
    if not attendees:
        return []  # No attendees list means no accepted attendees to report

    accepted = []

    for attendee in attendees:
        response_status = attendee.get('responseStatus', 'needsAction')
        if response_status in ['accepted', 'tentative']:
            email = attendee.get('email')
            if email:
                accepted.append(email)

    return accepted

def get_event_attachments(event: Dict[str, Any]) -> List[Dict[str, str]]:
    """Get event attachments."""
    attachments = event.get('attachments', [])
    result = []

    for attachment in attachments:
        attachment_info = {
            'title': attachment.get('title', ''),
            'fileUrl': attachment.get('fileUrl', ''),
            'mimeType': attachment.get('mimeType', '')
        }
        result.append(attachment_info)

    return result

def format_datetime(dt_str: str) -> tuple[str, str]:
    """Format datetime string to date and time components."""
    if not dt_str:
        return '', ''

    try:
        # Handle both datetime and date-only formats
        if 'T' in dt_str:
            # Parse full datetime
            if dt_str.endswith('Z'):
                dt = datetime.fromisoformat(dt_str[:-1] + '+00:00')
            else:
                dt = datetime.fromisoformat(dt_str)

            # Convert to local timezone if needed
            if dt.tzinfo is not None:
                dt = dt.astimezone()

            return dt.strftime('%Y-%m-%d'), dt.strftime('%H:%M:%S')
        else:
            # Date-only (all-day event)
            return dt_str, '00:00:00'
    except ValueError:
        return '', ''

def should_include_event(event: Dict[str, Any], user_email: str, now: datetime) -> bool:
    """
    Determine if an event should be included based on the filtering criteria.

    1. If the attendees list is not available, include the event.
    2. Otherwise, only consider including events I have been invited to.
    3. For events in the future, only include events I have not declined.
    """
    # Filter out workingLocation events
    if event.get('eventType') == 'workingLocation':
        return False

    # Check if user is invited
    if not is_user_invited(event, user_email):
        return False

    # For future events, check if user has declined
    event_start = event.get('start', {})
    start_time_str = event_start.get('dateTime') or event_start.get('date')

    if start_time_str:
        try:
            if 'T' in start_time_str:
                if start_time_str.endswith('Z'):
                    event_dt = datetime.fromisoformat(start_time_str[:-1] + '+00:00')
                else:
                    event_dt = datetime.fromisoformat(start_time_str)
                if event_dt.tzinfo is not None:
                    event_dt = event_dt.astimezone()
                else:
                    event_dt = event_dt.replace(tzinfo=timezone.utc).astimezone()
            else:
                # Date-only event
                event_dt = datetime.strptime(start_time_str, '%Y-%m-%d')
                event_dt = event_dt.replace(tzinfo=timezone.utc).astimezone()

            # If event is in the future and user has declined, exclude it
            if event_dt > now and has_user_declined(event, user_email):
                return False
        except ValueError:
            pass  # If we can't parse the date, include the event

    return True

def fetch_calendar_events(start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
    """Fetch calendar events from Google Calendar API."""
    creds = get_credentials()
    service = build('calendar', 'v3', credentials=creds)

    # Get user email
    user_email = get_user_email(service)
    print(f"Fetching events for: {user_email}", file=sys.stderr)

    # Convert datetime objects to RFC3339 format for API
    time_min = start_time.isoformat() + 'Z'
    time_max = end_time.isoformat() + 'Z'

    print(f"Date range: {start_time.strftime('%Y-%m-%d')} to {end_time.strftime('%Y-%m-%d')}", file=sys.stderr)

    try:
        # Call the Calendar API
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])
        print(f"Found {len(events)} total events", file=sys.stderr)

        # Filter and format events
        filtered_events = []
        now = datetime.now().astimezone()

        for event in events:
            if should_include_event(event, user_email, now):
                # Extract event details
                start = event.get('start', {})
                end = event.get('end', {})

                start_date, start_time_str = format_datetime(start.get('dateTime') or start.get('date'))
                end_date, end_time_str = format_datetime(end.get('dateTime') or end.get('date'))

                # Handle all-day events
                if not start_time_str or start_time_str == '00:00:00':
                    if start.get('date'):  # This is an all-day event
                        start_time_str = '00:00:00'
                        end_time_str = '23:59:59'

                formatted_event = {
                    'date': start_date,
                    'start_time': start_time_str,
                    'end_time': end_time_str,
                    'title': event.get('summary', 'No Title'),
                    'accepted_attendees': get_accepted_attendees(event),
                    'attachments': get_event_attachments(event)
                }

                filtered_events.append(formatted_event)

        print(f"Filtered to {len(filtered_events)} events", file=sys.stderr)
        return filtered_events

    except HttpError as error:
        print(f'An error occurred: {error}')
        return []

def main():
    parser = argparse.ArgumentParser(
        description='Fetch Google Calendar events in JSON format',
        epilog='''
Examples:
  %(prog)s                           # Next 2 weeks
  %(prog)s --start yesterday         # Yesterday to today
  %(prog)s --start "2 weeks ago"     # 2 weeks ago to today
  %(prog)s --start tomorrow          # Tomorrow for 2 weeks
  %(prog)s --start "next Monday"     # Next Monday for 2 weeks
  %(prog)s --start 2024-01-15        # From specific date
  %(prog)s --start yesterday --end "in 1 week"  # Custom range
        ''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--start', type=str,
                       help='Start date (supports "2 weeks ago", "yesterday", "next Monday", "2024-01-15", etc.)')
    parser.add_argument('--end', type=str,
                       help='End date (same formats as --start)')

    args = parser.parse_args()

    try:
        start_time, end_time = parse_date_arguments(args.start, args.end)
        events = fetch_calendar_events(start_time, end_time)

        # Output JSON
        output = {'events': events}
        print(json.dumps(output, indent=2, ensure_ascii=False))

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
