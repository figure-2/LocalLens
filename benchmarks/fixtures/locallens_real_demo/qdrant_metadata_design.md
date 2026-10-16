# Qdrant Metadata Design

The upgraded LocalLens search layer stores vectors in Qdrant and keeps source references such as relative path, page number, chunk number, image number, modality, and extractor profile. Search results are normalized into evidence packets for UI and Agent workflows.

Key terms: Qdrant, source_ref, evidence packet, vector payload, modality filter.
