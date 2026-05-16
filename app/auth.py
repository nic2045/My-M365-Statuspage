from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request

from app.config import settings

oauth = OAuth()
oauth.register(
    name="microsoft",
    client_id=settings.AZURE_CLIENT_ID,
    client_secret=settings.AZURE_CLIENT_SECRET,
    server_metadata_url=settings.oidc_metadata_url,
    client_kwargs={
        "scope": "openid profile email",
        "response_type": "code",
    },
)


class LoginRequired(Exception):
    def __init__(self, next_path: str = "/"):
        self.next_path = next_path


async def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


_DEV_USER = {"name": "Dev User", "email": "dev@localhost", "sub": "dev"}


async def require_auth(request: Request) -> dict:
    if settings.DISABLE_AUTH:
        return _DEV_USER
    user = await get_current_user(request)
    if user is None:
        raise LoginRequired(next_path=str(request.url.path))
    return user
