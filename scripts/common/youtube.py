"""YouTube Data API v3 helper - non-interactive, refresh-token based (no browser
consent at runtime, which GitHub Actions can't do). Generate the refresh token
once, locally, with scripts/setup_youtube_oauth.py, then store it as a secret.
"""
import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


def get_client():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"],
    )
    return build("youtube", "v3", credentials=creds)


def upload_video(video_path: str, title: str, description: str, tags: list[str], publish_at_iso: str) -> str:
    """Uploads as private with a scheduled publishAt buffer. Returns the video id."""
    youtube = get_client()
    body = {
        "snippet": {
            "title": title[:100], "description": description, "tags": tags,
            "categoryId": "27",  # Education - matches "AI tools / freelancing / side hustles" content
        },
        "status": {"privacyStatus": "private", "publishAt": publish_at_iso, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    return response["id"]


def set_thumbnail(video_id: str, thumbnail_path: str):
    youtube = get_client()
    youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg")).execute()
