"""CLI entrypoint for running the ingestion pipeline directly from the root workspace."""

import sys
from ingestion.pipeline import main

if __name__ == "__main__":
    main()
