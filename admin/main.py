from admin.app import create_app
from admin.config import settings_from_env

app = create_app(settings_from_env())
