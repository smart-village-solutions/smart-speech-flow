import requests


def get_health_status_html(service_urls):
    health_results = {}
    for name, url in service_urls.items():
        try:
            resp = requests.get(url, timeout=2)
            status = resp.json().get("status", "unbekannt")
        except Exception:
            status = "nicht erreichbar"
        health_results[name] = status
    health_html = "".join(
        [f"<li><b>{name}:</b> {status}</li>" for name, status in health_results.items()]
    )
    return health_html
