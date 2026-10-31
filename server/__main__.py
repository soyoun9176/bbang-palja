import argparse
import os

from .app import Application, Server


def main():
    parser = argparse.ArgumentParser(description="Kambodelight bakery event server")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        app = Application()
    except Exception as exc:
        parser.exit(1, f"서버 초기화 실패: {exc}\n")
    try:
        server = Server((args.host, args.port), app)
    except OSError as exc:
        parser.exit(1, f"서버 시작 실패 ({args.host}:{args.port}): {exc}\n")
    print(f"Kambodelight: http://{args.host}:{args.port} · staff /admin · database {'PostgreSQL' if app.db.postgres else app.db.path}", flush=True)
    if app.demo:
        print("로컬 데모 · 구매자 김소연 / 1234 · 예판 전화번호 01012345678", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
