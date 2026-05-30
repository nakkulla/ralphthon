from backend.app.models import ProfileCreate, normalize_csv, normalize_tech_stack


def test_normalize_tech_stack_lowercases_trims_and_dedupes():
    assert normalize_tech_stack([" FastAPI ", "fastapi", "PGVector", ""]) == ["fastapi", "pgvector"]


def test_normalize_csv_splits_trims_and_dedupes():
    assert normalize_csv(" music, ai, music ,, web ") == ["music", "ai", "web"]


def test_profile_create_normalizes_tech_stack():
    model = ProfileCreate(name="MoodBoard", tech_stack=[" Next.js ", "FASTAPI"])
    assert model.tech_stack == ["next.js", "fastapi"]
