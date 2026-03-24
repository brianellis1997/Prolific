"""One-time YouTube OAuth2 setup script.

Run this once to authenticate with YouTube and save credentials:
    PYTHONPATH=. python -m prolific.youtube.auth

This opens a browser for Google OAuth2 consent, then saves
the refresh token to youtube_credentials.json for future use.
"""

import json
import sys


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="Custom output path for credentials")
    args, _ = parser.parse_known_args()

    from prolific.core.config import settings

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Install google-auth-oauthlib: pip install google-auth-oauthlib")
        sys.exit(1)

    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.force-ssl",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]

    client_secrets = settings.youtube_client_secrets_path
    credentials_path = args.output or settings.youtube_credentials_path

    print(f"Client secrets file: {client_secrets}")
    print(f"Credentials will be saved to: {credentials_path}")
    print()
    print("A browser window will open for Google OAuth2 consent.")
    print("Sign in with the Google account that owns your YouTube channel.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(client_secrets, SCOPES)
    credentials = flow.run_local_server(port=8090)

    creds_data = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": SCOPES,
    }

    with open(credentials_path, "w") as f:
        json.dump(creds_data, f, indent=2)

    print(f"\nCredentials saved to {credentials_path}")
    print("The YouTube pipeline can now upload videos automatically.")


if __name__ == "__main__":
    main()
