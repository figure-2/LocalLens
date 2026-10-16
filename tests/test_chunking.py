from locallens.extractors.chunking import chunk_text


def test_chunking_is_deterministic():
    text = " ".join(str(i) for i in range(300))

    first = chunk_text(text, chunk_size=100, overlap=10)
    second = chunk_text(text, chunk_size=100, overlap=10)

    assert first == second
    assert len(first) > 1

