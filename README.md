# Google Calendar Events Fetcher

A Python script to fetch Google Calendar events and output them in JSON format with intelligent filtering.

## Features

- **OAuth2 Authentication**: Uses your existing Google credentials
- **Smart Date Logic**: Flexible date range handling
- **Event Filtering**: Excludes `workingLocation` events and applies attendee-based filtering
- **JSON Output**: Clean, structured output with event details

## Setup

1. **Prerequisites**: Ensure you have your Google Calendar API credentials in `~/.google/credentials.json`

2. **Install Dependencies**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **First Run**: The script will open a browser for OAuth authentication and save the token to `~/.google/token.json`

## Usage

```bash
# Default: Today to 2 weeks from today
./calendar_events.py

# Human-readable dates
./calendar_events.py --start yesterday
./calendar_events.py --start "2 weeks ago"
./calendar_events.py --start tomorrow
./calendar_events.py --start "next Monday"
./calendar_events.py --start "last Friday"

# Specific date formats
./calendar_events.py --start 2024-01-15
./calendar_events.py --start "Jan 15, 2024"

# Custom date ranges
./calendar_events.py --start yesterday --end "in 1 week"
./calendar_events.py --start "2 weeks ago" --end today
```

### Supported Date Formats

The script supports a wide variety of human-readable date formats:

- **Relative dates**: `yesterday`, `today`, `tomorrow`
- **Relative periods**: `2 weeks ago`, `3 days ago`, `1 month ago`
- **Future periods**: `in 2 days`, `in 1 week`, `in 3 months`
- **Named days**: `next Monday`, `last Friday`, `this Wednesday`
- **Standard formats**: `2024-01-15`, `Jan 15, 2024`, `15/01/2024`
- **And many more** thanks to the powerful `dateutil` library!

## Date Logic

- **No dates**: Today → Today + 2 weeks
- **Future start date**: Start date → Start date + 2 weeks
- **Past start date**: Start date → Today (inclusive)
- **End date provided**: Use the explicit range

## Event Filtering Rules

1. **workingLocation events**: Always excluded
2. **No attendees list**: Event is included
3. **Has attendees**: Only include if you're invited
4. **Future events**: Exclude if you've declined

## Output Format

```json
{
  "events": [
    {
      "date": "2024-01-15",
      "start_time": "09:00:00",
      "end_time": "10:00:00",
      "title": "Meeting Title",
      "accepted_attendees": ["user1@domain.com", "user2@domain.com"],
      "attachments": [
        {
          "title": "Document.pdf",
          "fileUrl": "https://...",
          "mimeType": "application/pdf"
        }
      ]
    }
  ]
}
```

## Notes

- All-day events show as `00:00:00` to `23:59:59`
- Times are displayed in local timezone
- Progress messages are sent to stderr, JSON output to stdout
- The script automatically detects your email address from the authenticated Google account
