"""Local structured identification and optional MAF conversation entry point."""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from uuid import uuid4

from ai_agent_lab.credit.bootstrap.composition import CreditApplication
from ai_agent_lab.credit.domain.models import IdentificationResult, Status


def render(result: IdentificationResult) -> str:
    """Render validated issuer facts for an analyst without a credit recommendation."""
    if result.status == Status.ERROR:
        return f"Identification failed: {result.error.message if result.error else 'unknown error'}"
    profiles = [result.company] if result.company else result.candidates
    lines = [f"EDGAR identification: {result.status}"]
    for company in profiles:
        tickers = ", ".join(listing.ticker for listing in company.listings) or "unavailable"
        lines.append(f"{company.legal_name} | CIK {company.cik} | tickers {tickers}")
    lines.extend(f"Warning: {warning}" for warning in result.warnings)
    lines.extend(f"SEC source: {source.url} (retrieved {source.retrieved_at.isoformat()})" for source in result.sources)
    lines.append("Issuer identification for analyst review; no credit decision.")
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> int:
    """Compose once, execute one local request and close on the owning task."""
    application = CreditApplication(args.config)
    try:
        if args.discover:
            print(json.dumps(await application.gateway.discover(), indent=2))
            return 0
        if args.message:
            agent = application.native_agent()
            response = await agent.run(args.message)
            print(response.text)
            return 0
        payload: dict[str, object] = {"query": args.query or "", "query_type": args.query_type}
        if args.selected_cik:
            payload["selected_cik"] = args.selected_cik
        result = await application.identify(payload, uuid4().hex)
        print(result.model_dump_json(indent=2) if args.json else render(result))
        return 1 if result.status == Status.ERROR else 0
    finally:
        await application.aclose()


def main() -> None:
    """Parse explicit analyst input; model credentials are only needed for --message."""
    parser = argparse.ArgumentParser(description="Corporate Credit Analyst: SEC issuer identification")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--query")
    mode.add_argument("--message")
    mode.add_argument("--discover", action="store_true")
    parser.add_argument("--query-type", choices=["auto", "name", "ticker", "cik"], default="auto")
    parser.add_argument("--selected-cik")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--json", action="store_true")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
