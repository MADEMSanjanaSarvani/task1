"""Run this ONCE, locally, on your own machine - not in GitHub Actions.

GitHub Actions runners can't open a browser for interactive OAuth consent, so
the pipeline authenticates non-interactively with a long-lived refresh token
instead. This script does the one-time interactive consent flow and prints the
refresh token to save as the YOUTUBE_REFRESH_TOKEN GitHub secret.

Usage:
    pip install google-auth-oauthlib
    python scripts/setup_youtube_oauth.py --client-id ... --client-secret ...

Follow the browser prompt, sign in with the Google account that owns the target
YouTube channel, and approve the consent screen. See README section 9 for how to
create the OAuth client (Client ID/Secret) in Google Cloud Console first.
"""
import argparse

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    args = parser.parse_args()

    client_config = {
        "installed": {
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n" + "=" * 60)
    print("Save this as the YOUTUBE_REFRESH_TOKEN GitHub secret:")
    print(creds.refresh_token)
    print("=" * 60)
    print(
        "\nAlso save YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET (the values you "
        "passed to this script) as GitHub secrets with those exact names."
    )


if __name__ == "__main__":
    main()
