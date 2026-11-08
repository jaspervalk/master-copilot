from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[4]
DATA_DIR = ROOT_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    project_name: str = "Master Copilot API"
    api_v1_prefix: str = "/api"
    database_url: str = f"sqlite:///{DATA_DIR / 'app.db'}"
    data_dir: Path = DATA_DIR
    corpus_dir: Path = ROOT_DIR / "corpus"
    qdrant_local_path: Path = DATA_DIR / "qdrant"
    # De evalset staat in git, naast corpus/ en data/; de runs niet.
    eval_dir: Path = ROOT_DIR / "eval"
    eval_runs_dir: Path = DATA_DIR / "eval" / "runs"
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_collection_name: str = "study_chunks"
    qdrant_timeout_seconds: int = 60
    qdrant_upsert_batch_size: int = 16
    openai_api_key: str | None = None
    openai_answer_model: str = "gpt-4.1-mini"
    openai_rewrite_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-large"
    openai_embedding_dimensions: int = 1024
    # OpenAI kapt een embeddingrequest af op 300.000 tokens en 2048 invoeren.
    # Een tekstboek is ruim groter dan dat, dus de aanroep wordt gebatcht; de
    # marge onder de harde grens vangt de schatting hieronder op.
    openai_embedding_max_tokens_per_request: int = 250_000
    openai_embedding_max_inputs_per_request: int = 512
    local_embedding_dimensions: int = 256
    default_query_limit: int = 8
    # Alleen toegepast wanneer de embeddings van OpenAI komen; hash-embeddings
    # leveren scores die niet met deze drempel te vergelijken zijn.
    min_evidence_score: float = 0.20
    # Oefenmodus: hoe lang een uitdrukking mag draaien voordat hij wordt
    # afgekapt. Geen beveiliging, wel een rem op een oneindige lus. Ruim
    # gekozen omdat de interpreterstart en het laden van numpy erin zitten;
    # een koude eerste run haalde vijf seconden niet.
    practice_timeout_seconds: int = 15
    max_upload_size_bytes: int = 100 * 1024 * 1024
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    # Canvas (agenda). Zonder allebei werkt de agenda op eigen taken en
    # course.yml alleen. Het token is alleen-lezen bedoeld en komt nergens in
    # een log of antwoord terecht.
    canvas_base_url: str | None = None
    canvas_access_token: str | None = None
    canvas_timeout_seconds: int = 30
    # Ouder dan dit en de agendapagina synchroniseert zelf: er draait geen
    # planner in de app.
    canvas_stale_after_minutes: int = 30
    # Deadlinemeldingen op je telefoon (`cli notify`). Het topic is het geheim:
    # wie de naam kent, leest mee. Leeg = geen meldingen.
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str | None = None

    @property
    def use_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def trash_dir(self) -> Path:
        return self.corpus_dir / ".trash"

    def prepare_runtime_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.corpus_dir.mkdir(parents=True, exist_ok=True)
        self.qdrant_local_path.mkdir(parents=True, exist_ok=True)


settings = Settings()
