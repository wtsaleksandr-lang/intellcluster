from fastapi.testclient import TestClient

from main_data import app

client = TestClient(app)


def run() -> int:
    checks = [
        ("/data", 200),
        ("/data/search", 200),
        ("/data/search?type=Importer&province=ON&sort=buyer_score", 200),
        ("/data/search?city=Toronto&incorporated_from=2010&incorporated_to=2026&website=yes", 200),
        ("/data/search?hs=8708&origin=China&page=2", 200),
        ("/data/search?sort=newest", 200),
        ("/data/suggest?q=map", 200),
        ("/data/company/maple-auto-supply-inc", 200),
        ("/data/company/maple-auto-supply-inc/export.csv", 200),
        ("/api/intelligence/health", 200),
        ("/api/intelligence/sources", 200),
    ]
    failed = []
    for path, expected in checks:
        response = client.get(path, follow_redirects=False)
        if response.status_code != expected:
            failed.append(f"{path}: {response.status_code} != {expected}")
    if failed:
        print("Intelligence UI smoke FAILED")
        print("\n".join(failed))
        return 1
    print(f"Intelligence UI smoke OK: {len(checks)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
