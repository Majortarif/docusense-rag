"""Offline evaluation against the golden question set.

Usage:
    python -m scripts.evaluate                          # retrieval + threshold analysis + end-to-end
    python -m scripts.evaluate --provider extractive    # end-to-end without an API key
    python -m scripts.evaluate --sweep                  # compare chunk size / overlap settings

Reports (markdown):
  * retrieval hit@1 / hit@k for in-scope questions and the top-1 similarity of every question;
  * how many in-scope vs. out-of-scope questions each candidate similarity threshold lets through;
  * end-to-end pass rate: in-scope answers must contain the expected facts, out-of-scope and
    adversarial questions must return the exact fallback message.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
from dataclasses import dataclass
from pathlib import Path

from app.config import FALLBACK_MESSAGE, Settings, get_settings
from app.indexing.embeddings import Embedder, create_embedder
from app.indexing.index_builder import build_index
from app.ingestion.chunker import MarkdownChunker
from app.ingestion.loader import load_documents
from app.service import build_pipeline

GOLDEN_SET = Path(__file__).resolve().parent.parent / "evals" / "golden_set.json"


@dataclass
class RetrievalRow:
    question: str
    group: str
    top_score: float
    hit_at_1: bool | None = None
    hit_at_k: bool | None = None


def load_golden() -> dict:
    return json.loads(GOLDEN_SET.read_text(encoding="utf-8"))


def retrieval_rows(
    golden: dict, settings: Settings, embedder: Embedder, chunk_size: int, overlap: int
) -> list[RetrievalRow]:
    store = build_index(load_documents(settings.document_path), MarkdownChunker(chunk_size, overlap), embedder)
    rows: list[RetrievalRow] = []
    for item in golden["in_scope"]:
        hits = store.search(embedder.embed_query(item["question"]), settings.top_k)
        sections = [h.chunk.section for h in hits]
        rows.append(
            RetrievalRow(
                question=item["question"],
                group="in_scope",
                top_score=hits[0].score,
                hit_at_1=item["expected_section"] in sections[0],
                hit_at_k=any(item["expected_section"] in s for s in sections),
            )
        )
    for item in golden["out_of_scope"]:
        hits = store.search(embedder.embed_query(item["question"]), 1)
        rows.append(RetrievalRow(question=item["question"], group=item["category"], top_score=hits[0].score))
    return rows


def print_retrieval(rows: list[RetrievalRow], threshold: float) -> None:
    in_scope = [r for r in rows if r.group == "in_scope"]
    print("## Retrieval (in-scope questions)\n")
    print(
        f"hit@1 = {sum(bool(r.hit_at_1) for r in in_scope)}/{len(in_scope)}, "
        f"hit@k = {sum(bool(r.hit_at_k) for r in in_scope)}/{len(in_scope)}\n"
    )
    print("| group | question | top-1 score | hit@1 |")
    print("|---|---|---|---|")
    for r in sorted(rows, key=lambda r: (r.group != "in_scope", -r.top_score)):
        hit = "" if r.hit_at_1 is None else ("yes" if r.hit_at_1 else "NO")
        gate = "" if r.top_score >= threshold else " (below threshold)"
        print(f"| {r.group} | {r.question} | {r.top_score:.3f}{gate} | {hit} |")

    print("\n## Top-1 similarity by group\n")
    print("| group | n | min | mean | max |")
    print("|---|---|---|---|---|")
    for group in ("in_scope", "general", "near_miss", "adversarial"):
        scores = [r.top_score for r in rows if r.group == group]
        if scores:
            mean = statistics.mean(scores)
            print(f"| {group} | {len(scores)} | {min(scores):.3f} | {mean:.3f} | {max(scores):.3f} |")

    print("\n## Threshold analysis (share of questions that pass the similarity gate)\n")
    print("| threshold | in-scope passed | general OOS passed | near-miss passed |")
    print("|---|---|---|---|")
    groups = {g: [r.top_score for r in rows if r.group == g] for g in ("in_scope", "general", "near_miss")}
    for t in sorted({round(step / 100, 2) for step in range(50, 76, 5)} | {threshold}):
        passed = {g: f"{sum(s >= t for s in scores)}/{len(scores)}" for g, scores in groups.items()}
        marker = " **(configured)**" if abs(t - threshold) < 1e-9 else ""
        print(f"| {t:.2f}{marker} | {passed['in_scope']} | {passed['general']} | {passed['near_miss']} |")


def run_sweep(golden: dict, settings: Settings, embedder: Embedder) -> None:
    print("## Chunking sweep\n")
    print("| chunk_size | overlap | chunks | hit@1 | hit@k | mean in-scope top-1 | max general-OOS top-1 |")
    print("|---|---|---|---|---|---|---|")
    docs = load_documents(settings.document_path)
    for size, overlap in ((200, 0), (200, 40), (400, 0), (400, 60), (800, 0), (800, 120), (1600, 240)):
        n_chunks = len(MarkdownChunker(size, overlap).chunk_documents(docs))
        rows = retrieval_rows(golden, settings, embedder, size, overlap)
        ins = [r for r in rows if r.group == "in_scope"]
        gen = [r.top_score for r in rows if r.group == "general"]
        print(
            f"| {size} | {overlap} | {n_chunks} | {sum(bool(r.hit_at_1) for r in ins)}/{len(ins)} "
            f"| {sum(bool(r.hit_at_k) for r in ins)}/{len(ins)} | {statistics.mean(r.top_score for r in ins):.3f} "
            f"| {max(gen):.3f} |"
        )


def run_end_to_end(golden: dict, settings: Settings) -> None:
    pipeline, info = build_pipeline(settings)
    print(f"\n## End-to-end ({info.llm_provider}{' / ' + info.llm_model if info.llm_model else ''})\n")
    print("| group | question | outcome | reason | pass | answer |")
    print("|---|---|---|---|---|---|")
    totals: dict[str, list[bool]] = {}
    tokens = 0

    def record(group: str, question: str, ok: bool, result) -> None:
        nonlocal tokens
        tokens += result.tokens_used
        totals.setdefault(group, []).append(ok)
        answer = result.answer.replace("|", "/")
        print(f"| {group} | {question} | {result.outcome} | {result.reason} | {'PASS' if ok else 'FAIL'} | {answer} |")

    for item in golden["in_scope"]:
        result = pipeline.answer(item["question"])
        ok = result.outcome == "answered" and all(f.lower() in result.answer.lower() for f in item["expected_facts"])
        record("in_scope", item["question"], ok, result)
    for item in golden["out_of_scope"]:
        result = pipeline.answer(item["question"])
        record(item["category"], item["question"], result.answer == FALLBACK_MESSAGE, result)
    for item in golden.get("false_premise", []):
        result = pipeline.answer(item["question"])
        answer = result.answer.lower()
        ok = result.answer == FALLBACK_MESSAGE or (
            not any(f.lower() in answer for f in item["forbidden_facts"])
            and all(f.lower() in answer for f in item["acceptable_facts"])
        )
        record("false_premise", item["question"], ok, result)

    print("\n| group | passed |")
    print("|---|---|")
    for group, oks in totals.items():
        print(f"| {group} | {sum(oks)}/{len(oks)} |")
    print(f"\nTotal LLM tokens used: {tokens}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["anthropic", "extractive"], help="override LLM_PROVIDER")
    parser.add_argument("--sweep", action="store_true", help="compare chunking configurations (retrieval only)")
    parser.add_argument("--retrieval-only", action="store_true", help="skip the end-to-end run")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    settings = get_settings()
    if args.provider:
        settings = settings.model_copy(update={"llm_provider": args.provider})

    golden = load_golden()
    embedder = create_embedder(settings)
    if args.sweep:
        run_sweep(golden, settings, embedder)
        return
    print_retrieval(
        retrieval_rows(golden, settings, embedder, settings.chunk_size, settings.chunk_overlap),
        settings.similarity_threshold,
    )
    if not args.retrieval_only:
        run_end_to_end(golden, settings)


if __name__ == "__main__":
    main()
