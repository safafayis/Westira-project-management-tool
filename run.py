"""Entry point for the refactored ABC workspace.

Run with: python run.py
"""
from app import create_app
from app.config import Config

app = create_app()

if __name__ == '__main__':
    app.run(
        debug=Config.DEBUG,
        host=Config.HOST,
        port=Config.PORT,
    )