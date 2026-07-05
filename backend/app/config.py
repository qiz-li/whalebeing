from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    aisstream_api_key: str = ""
    database_url: str = "postgresql://postgres:postgres@localhost:5432/whalebeing"

    class Config:
        env_file = ".env"


settings = Settings()
