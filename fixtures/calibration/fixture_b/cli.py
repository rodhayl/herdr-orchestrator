#!/usr/bin/env python3
"""CLI for Fixture B Event Store."""
import argparse
import json
import sys
import uuid
from models import Event
from store import EventStore


def main():
    parser = argparse.ArgumentParser(description="Event store CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    app_p = sub.add_parser("append")
    app_p.add_argument("--db", default="events.jsonl")
    app_p.add_argument("--type", required=True)
    app_p.add_argument("--payload", required=True)

    query_p = sub.add_parser("query")
    query_p.add_argument("--db", default="events.jsonl")
    query_p.add_argument("--type", required=True)

    args = parser.parse_args()
    store = EventStore(args.db)

    if args.command == "append":
        ev = Event(event_id=str(uuid.uuid4())[:8], event_type=args.type, payload=json.loads(args.payload))
        store.append(ev)
        print(f"Appended: {ev.event_id}")
    elif args.command == "query":
        events = store.query_by_type(args.type)
        print(json.dumps([e.to_dict() for e in events]))


if __name__ == "__main__":
    main()
