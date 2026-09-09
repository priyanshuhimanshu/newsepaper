from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # App
    data_dir: Path = Field(default=Path("data"))
    pdf_output_dir: Path = Field(default=Path("data/epapers"))
    log_level: str = Field(default="INFO")

    # Scheduling
    timezone: str = "Asia/Kolkata"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def get_settings() -> Settings:
    return Settings()
