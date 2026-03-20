"""One-shot script to re-authorize YouTube OAuth credentials."""

import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

CLIENT_SECRETS = "./client_secrets.json"
CREDENTIALS_OUT = "./youtube_credentials.json"


def main():
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
    creds = flow.run_local_server(port=8080, open_browser=True)

    creds_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes),
    }

    Path(CREDENTIALS_OUT).write_text(json.dumps(creds_data, indent=2))
    print(f"Saved fresh credentials to {CREDENTIALS_OUT}")
    print(f"Scopes granted: {list(creds.scopes)}")


if __name__ == "__main__":
    main()
