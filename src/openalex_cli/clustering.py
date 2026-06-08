"""Embeddings (OpenAI) + clustering (HDBSCAN/KMeans) y descripción con GPT.

Dos estrategias:
  - sin k → HDBSCAN: descubre el nº de clusters por densidad y marca outliers.
  - con k → KMeans con ese k (override explícito).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import mean

import numpy as np
from openai import OpenAI
from sklearn.cluster import HDBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import normalize

from .client import Work

# Etiqueta de outliers (HDBSCAN asigna -1 a los puntos que no forman cluster).
NOISE_LABEL = -1


def embed_works(
    works: list[Work], api_key: str, model: str, batch_size: int = 256
) -> np.ndarray:
    """Devuelve una matriz (n_works, dim) con los embeddings de cada work."""
    from .ssl_setup import ensure_system_trust

    ensure_system_trust()
    client = OpenAI(api_key=api_key)
    texts = [w.text_for_embedding or w.title for w in works]
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        chunk = texts[start : start + batch_size]
        resp = client.embeddings.create(model=model, input=chunk)
        vectors.extend(d.embedding for d in resp.data)
    return np.array(vectors, dtype=np.float32)


@dataclass
class Cluster:
    label: int
    works: list[Work]
    top_topics: list[tuple[str, int]]
    top_fields: list[tuple[str, int]]
    top_domains: list[tuple[str, int]]
    top_keywords: list[tuple[str, int]]
    total_citations: int
    mean_citations: float
    mean_fwci: float | None
    n_top_10_percent: int  # nº de works en el top-10% de su campo/año
    representatives: list[Work]  # más cercanos al centroide
    is_noise: bool = False  # cluster de outliers (HDBSCAN label -1)
    description: str | None = None  # descripción generada con GPT (opcional)

    @property
    def size(self) -> int:
        return len(self.works)


def _representatives(
    works: list[Work], embeddings: np.ndarray, centroid: np.ndarray, n: int = 3
) -> list[Work]:
    dists = np.linalg.norm(embeddings - centroid, axis=1)
    order = np.argsort(dists)[:n]
    return [works[i] for i in order]


# Nº de componentes tras reducir antes de HDBSCAN. La densidad no es fiable en 1536
# dims (HDBSCAN sobre-marca outliers); reducir a pocas dims lo corrige. Verificado en
# varios datasets: ~5 dims minimiza falsos outliers de forma estable.
REDUCE_COMPONENTS = 5


# Por debajo de este N, UMAP es inestable (pocos puntos para aprender la variedad);
# 'auto' usa PCA. A partir de aquí, 'auto' usa UMAP, que captura mejor la estructura.
UMAP_MIN_SAMPLES = 50


def _reduce(embeddings: np.ndarray, method: str, n_components: int) -> np.ndarray:
    """Reduce dimensionalidad antes de HDBSCAN. method: 'auto'|'umap'|'pca'|'none'.

    - 'auto' (def.): PCA si N<UMAP_MIN_SAMPLES, UMAP si no (robusto en datasets
      pequeños, mejor estructura en grandes).
    - 'umap': preserva mejor la estructura local (estándar BERTopic), pero necesita
      suficientes puntos.
    - 'pca': lineal, estable y sin dependencias pesadas.
    - 'none': clusteriza sobre los embeddings completos (no recomendado en 1536 dims).
    """
    n = len(embeddings)
    comps = min(n_components, n - 1, embeddings.shape[1])
    if method == "auto":
        method = "umap" if n >= UMAP_MIN_SAMPLES else "pca"
    if method == "none":
        return embeddings
    if method == "pca":
        return PCA(n_components=comps, random_state=42).fit_transform(embeddings)
    if method == "umap":
        import warnings

        import umap  # diferido: arrastra numba y es lento de importar

        # n_neighbors escalado con N (15 es demasiado en datasets pequeños).
        n_neighbors = min(15, max(2, n // 3))
        reducer = umap.UMAP(
            n_components=comps,
            n_neighbors=n_neighbors,
            metric="cosine",
            random_state=42,  # reproducible (desactiva paralelismo: warning esperado)
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return reducer.fit_transform(embeddings)
    raise ValueError(f"Método de reducción desconocido: {method}")


def _assign_labels(
    embeddings: np.ndarray,
    k: int | None,
    min_cluster_size: int,
    reduce: str = "auto",
    n_components: int = REDUCE_COMPONENTS,
) -> np.ndarray:
    """k fijo → KMeans; sin k → HDBSCAN (descubre nº de clusters por densidad).

    Para HDBSCAN reducimos primero la dimensionalidad (`reduce`) y normalizamos (L2),
    de modo que la distancia euclídea equivale a coseno.
    """
    if k is not None:
        k = max(1, min(k, len(embeddings)))
        return KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(embeddings)

    reduced = _reduce(embeddings, reduce, n_components)
    unit = normalize(reduced)
    size = max(2, min(min_cluster_size, len(embeddings)))
    return HDBSCAN(
        min_cluster_size=size, min_samples=1, metric="euclidean", copy=True
    ).fit_predict(unit)


def cluster_works(
    works: list[Work],
    embeddings: np.ndarray,
    k: int | None = None,
    min_cluster_size: int = 2,
    reduce: str = "auto",
) -> tuple[list[Cluster], int]:
    """Agrupa los works y resume el impacto de cada cluster.

    Devuelve (clusters, n_clusters). Con HDBSCAN puede aparecer un cluster de
    outliers (label -1), que se coloca al final y no cuenta en n_clusters.
    """
    if len(works) < 2:
        raise ValueError("Se necesitan al menos 2 artículos para clusterizar.")

    labels = _assign_labels(embeddings, k, min_cluster_size, reduce=reduce)

    clusters: list[Cluster] = []
    for lbl in sorted(set(labels)):
        idxs = [i for i, x in enumerate(labels) if x == lbl]
        members = [works[i] for i in idxs]
        member_emb = embeddings[idxs]
        centroid = member_emb.mean(axis=0)
        cites = [w.cited_by_count for w in members]
        fwcis = [w.fwci for w in members if w.fwci is not None]
        topic_counts = Counter(w.topic for w in members if w.topic)
        field_counts = Counter(w.field for w in members if w.field)
        domain_counts = Counter(w.domain for w in members if w.domain)
        keyword_counts = Counter(kw for w in members for kw in w.keywords)

        clusters.append(
            Cluster(
                label=int(lbl),
                works=members,
                top_topics=topic_counts.most_common(3),
                top_fields=field_counts.most_common(3),
                top_domains=domain_counts.most_common(2),
                top_keywords=keyword_counts.most_common(5),
                total_citations=sum(cites),
                mean_citations=mean(cites) if cites else 0.0,
                mean_fwci=mean(fwcis) if fwcis else None,
                n_top_10_percent=sum(1 for w in members if w.is_top_10_percent),
                representatives=_representatives(members, member_emb, centroid),
                is_noise=(lbl == NOISE_LABEL),
            )
        )

    n_clusters = sum(1 for c in clusters if not c.is_noise)
    # Orden por impacto (citas totales) desc; outliers siempre al final.
    clusters.sort(key=lambda c: (c.is_noise, -c.total_citations))
    return clusters, n_clusters


def _cluster_prompt(cluster: Cluster, max_articles: int, abstract_chars: int) -> str:
    lines: list[str] = []
    for w in cluster.works[:max_articles]:
        abstract = (w.abstract or "").strip().replace("\n", " ")
        if abstract:
            abstract = abstract[:abstract_chars]
        lines.append(f"- «{w.title}»\n  {abstract or '(sin abstract)'}")
    return (
        "Eres un analista de literatura científica. A partir de los siguientes "
        "artículos (título y abstract) que pertenecen a un mismo cluster temático, "
        "redacta en español una descripción de 2-3 frases que capture el tema común, "
        "el enfoque metodológico y qué los une. No enumeres los artículos uno a uno; "
        "sintetiza. Sé concreto.\n\nArtículos:\n" + "\n".join(lines)
    )


def describe_clusters(
    clusters: list[Cluster],
    api_key: str,
    model: str,
    max_articles: int = 8,
    abstract_chars: int = 700,
) -> None:
    """Rellena `cluster.description` con una síntesis generada por GPT (in place).

    Una llamada por cluster, sobre los abstracts de sus artículos.
    """
    client = OpenAI(api_key=api_key)
    for cluster in clusters:
        prompt = _cluster_prompt(cluster, max_articles, abstract_chars)
        resp = client.responses.create(
            model=model,
            input=prompt,
            max_output_tokens=400,
        )
        cluster.description = (resp.output_text or "").strip() or None
