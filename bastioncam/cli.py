from __future__ import annotations

import argparse
import logging
import os
import socket
import threading

from .collector import collect_forever, collect_once
from .db import connect
from .llm import build_segments, enrich_loop, enrich_pending
from .security import scrub_database
from .remote import poll_config, push_pending
from .web import serve


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bastioncam")
    p.add_argument("--db", default="history.db", help="SQLite database path")
    sub = p.add_subparsers(dest="command", required=True)
    token_default = os.environ.get("BASTIONCAM_TOKEN", "")
    once = sub.add_parser("collect-once"); once.add_argument("--server-url"); once.add_argument("--token", default=token_default)
    collect = sub.add_parser("collect"); collect.add_argument("--interval", type=float, default=5); collect.add_argument("--server-url"); collect.add_argument("--token", default=token_default)
    sync = sub.add_parser("sync"); sync.add_argument("--server-url", required=True); sync.add_argument("--token", default=token_default); sync.add_argument("--limit", type=int, default=100)
    web = sub.add_parser("serve"); web.add_argument("--host", default="127.0.0.1"); web.add_argument("--port", type=int, default=8787); web.add_argument("--ollama-url", default="http://127.0.0.1:11434"); web.add_argument("--embed-model", default="nomic-embed-text")
    run = sub.add_parser("run"); run.add_argument("--interval", type=float, default=5); run.add_argument("--host", default="127.0.0.1"); run.add_argument("--port", type=int, default=8787); run.add_argument("--ollama-url", default="http://127.0.0.1:11434"); run.add_argument("--embed-model", default="nomic-embed-text")
    llm = sub.add_parser("enrich"); llm.add_argument("--url", default="http://127.0.0.1:11434"); llm.add_argument("--chat-model", default="qwen3:4b"); llm.add_argument("--embed-model", default="nomic-embed-text"); llm.add_argument("--limit", type=int, default=5); llm.add_argument("--settle", type=int, default=45)
    loop = sub.add_parser("enrich-loop"); loop.add_argument("--url", default="http://127.0.0.1:11434"); loop.add_argument("--chat-model", default="qwen3:4b"); loop.add_argument("--embed-model", default="nomic-embed-text"); loop.add_argument("--batch", type=int, default=2); loop.add_argument("--interval", type=int, default=30); loop.add_argument("--settle", type=int, default=45)
    sub.add_parser("stats")
    sub.add_parser("scrub", help="irreversibly redact secrets already stored in the database")
    return p


def main() -> None:
    args = parser().parse_args(); logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "collect-once":
        print("panes=%d snapshots=%d" % collect_once(args.db))
        if args.server_url:
            config=poll_config(args.db,args.server_url,args.token)
            print(f"delivered={push_pending(args.db,args.server_url,args.token,config_revision=config['config_revision'])}")
    elif args.command == "collect": collect_forever(args.db, args.interval, args.server_url, args.token)
    elif args.command == "sync":
        config=poll_config(args.db,args.server_url,args.token)
        print(f"delivered={push_pending(args.db,args.server_url,args.token,args.limit,config_revision=config['config_revision'])}")
    elif args.command == "serve": serve(args.db, args.host, args.port, args.ollama_url, args.embed_model)
    elif args.command == "run":
        threading.Thread(target=collect_forever,
                         args=(args.db,args.interval,None,"",socket.gethostname()),daemon=True).start()
        serve(args.db, args.host, args.port, args.ollama_url, args.embed_model)
    elif args.command == "enrich":
        db = connect(args.db)
        try:
            created = build_segments(db, settle_seconds=args.settle)
            done = enrich_pending(db,args.url,args.chat_model,args.embed_model,args.limit)
            print(f"segments_created={created} enriched={done}")
        finally: db.close()
    elif args.command == "enrich-loop":
        enrich_loop(args.db,args.url,args.chat_model,args.embed_model,args.interval,args.settle,args.batch)
    elif args.command == "stats":
        db = connect(args.db)
        print(dict(db.execute("""SELECT (SELECT count(*) FROM panes) panes,
          (SELECT count(*) FROM snapshots) snapshots,
          (SELECT count(*) FROM segments) segments,
          (SELECT count(*) FROM segments WHERE status='done') enriched,
          (SELECT count(*) FROM segments WHERE status IN ('pending','retry','processing')) queued,
          (SELECT count(*) FROM period_summaries WHERE period_type='hour') hour_summaries,
          (SELECT count(*) FROM period_summaries WHERE period_type='day') day_summaries""").fetchone()))
        db.close()
    elif args.command == "scrub":
        db = connect(args.db)
        try: print(scrub_database(db))
        finally: db.close()


if __name__ == "__main__": main()
