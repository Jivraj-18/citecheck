"""SciFact eval set: expert-written claims paired with a cited abstract and an
expert label (supports / contradicts / not_enough_info).

Source: https://github.com/allenai/scifact (CC BY-NC 2.0). Only the train and
dev splits have labels; the test split is unlabelled and is not used.
A cited document with no evidence annotation is NOT_ENOUGH_INFO by the
dataset's definition.
"""

import json
import random
import tarfile
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "cache" / "scifact"
URL = "https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz"
LABELS = {"SUPPORT": "supports", "CONTRADICT": "contradicts", "NOT_ENOUGH_INFO": "not_enough_info"}


def download() -> Path:
    data_dir = RAW_DIR / "data"
    if not (data_dir / "corpus.jsonl").exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        archive = RAW_DIR / "data.tar.gz"
        urllib.request.urlretrieve(URL, archive)
        with tarfile.open(archive) as tar:
            tar.extractall(RAW_DIR, filter="data")
    return data_dir


def all_pairs(data_dir: Path) -> list[dict]:
    corpus = {}
    for line in (data_dir / "corpus.jsonl").read_text().splitlines():
        doc = json.loads(line)
        corpus[doc["doc_id"]] = doc
    pairs = []
    for split in ("train", "dev"):
        for line in (data_dir / f"claims_{split}.jsonl").read_text().splitlines():
            claim = json.loads(line)
            for doc_id in claim["cited_doc_ids"]:
                evidence = claim["evidence"].get(str(doc_id))
                labels = {e["label"] for e in evidence} if evidence else {"NOT_ENOUGH_INFO"}
                if len(labels) != 1:  # mixed evidence for one doc: ambiguous, skip
                    continue
                doc = corpus[doc_id]
                pairs.append({
                    "id": f"scifact/{split}/{claim['id']}/{doc_id}",
                    "dataset": "scifact",
                    "claim": claim["claim"],
                    "cited_title": doc["title"],
                    "cited_abstract": " ".join(doc["abstract"]),
                    "label": LABELS[labels.pop()],
                })
    return pairs


def sample(pairs: list[dict], per_label: int, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for label in LABELS.values():
        group = [p for p in pairs if p["label"] == label]
        out += rng.sample(group, per_label)
    rng.shuffle(out)
    return out


def build(out_path: Path, per_label: int = 100, seed: int = 0) -> dict:
    pairs = all_pairs(download())
    items = sample(pairs, per_label, seed)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(i) + "\n" for i in items))
    return {"available": dict(Counter(p["label"] for p in pairs)), "sampled": dict(Counter(i["label"] for i in items))}
