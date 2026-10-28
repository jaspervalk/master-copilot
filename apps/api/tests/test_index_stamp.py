import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.services.index_stamp import IndexStamp, StampMismatchError, read_stamp, validate_or_raise, write_stamp


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'stamp.db'}", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_validate_or_raise_passes_when_no_stamp_exists():
    validate_or_raise(None, provider="openai", model="text-embedding-3-large", dimensions=1024)


def test_validate_or_raise_passes_on_match():
    stamp = IndexStamp(name="policy_chunks", provider="openai", model="text-embedding-3-large", dimensions=1024)

    validate_or_raise(stamp, provider="openai", model="text-embedding-3-large", dimensions=1024)


def test_validate_or_raise_rejects_provider_mismatch():
    stamp = IndexStamp(name="policy_chunks", provider="openai", model="text-embedding-3-large", dimensions=1024)

    with pytest.raises(StampMismatchError):
        validate_or_raise(stamp, provider="local-hash", model="md5-bucket", dimensions=256)


def test_validate_or_raise_rejects_model_mismatch():
    stamp = IndexStamp(name="policy_chunks", provider="openai", model="text-embedding-3-large", dimensions=1024)

    with pytest.raises(StampMismatchError):
        validate_or_raise(stamp, provider="openai", model="text-embedding-3-small", dimensions=1024)


def test_write_then_read_stamp_roundtrip(tmp_path):
    db = _session(tmp_path)
    write_stamp(db, name="policy_chunks", provider="openai", model="text-embedding-3-large", dimensions=1024)

    stamp = read_stamp(db, "policy_chunks")

    assert stamp is not None
    assert stamp.provider == "openai"
    assert stamp.model == "text-embedding-3-large"
    assert stamp.dimensions == 1024


def test_write_stamp_updates_existing_row(tmp_path):
    db = _session(tmp_path)
    write_stamp(db, name="policy_chunks", provider="openai", model="text-embedding-3-large", dimensions=1024)
    write_stamp(db, name="policy_chunks", provider="local-hash", model="md5-bucket", dimensions=256)

    stamp = read_stamp(db, "policy_chunks")

    assert stamp.provider == "local-hash"
    assert stamp.dimensions == 256
