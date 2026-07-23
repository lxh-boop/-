from __future__ import annotations

import argparse
import json

from .rag_quality import evaluate_retrieval, load_cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate saved RAG retrieval results.")
    parser.add_argument("cases", help="JSON file containing retrieval cases")
    args = parser.parse_args()
    metrics = evaluate_retrieval(load_cases(args.cases))
    print(json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
