import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Wexira application configuration.

    Sensitive values (DATABASE_URL, SECRET_KEY) are read from environment
    variables so they are never committed to the repository.
    """

    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL', 'postgresql://wexira:wexira@127.0.0.1:5432/wexira'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv('SECRET_KEY', 'wexira-secret')

    # Run settings
    DEBUG = os.getenv('FLASK_DEBUG', '1') == '1'
    HOST = '127.0.0.1'
    PORT = 5000
