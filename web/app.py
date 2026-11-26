"""Interfaz web (Jinja2 + htmx): búsqueda y valoración de resultados (sección
10 del design spec, FR-014), cuentas, suscripciones y bandeja de avisos.

It only talks to the API of the backend. The session of a user is the one of the
API: its cookie is set again for the address of the web, out of the reach of
scripts. Every page works without scripts, except searching."""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData

BACKEND_URL = os.environ.get("BACKEND_INTERNAL_URL", "http://backend:8000")
HERE = Path(__file__).resolve().parent
SESSION_COOKIE = "contextcrawl_sesion"
SESSION_SECONDS = 14 * 24 * 3600  # as in the API
PAGE = 20  # entries of the inbox
SAME_SITE = {"same-origin", "none"}

app = FastAPI(title="ContextCrawl web")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


def safe_url(url: str | None) -> str | None:
    """The address of a document comes from outside: only web ones become links."""
    return url if url and url.startswith(("https://", "http://")) else None


templates.env.filters["safe_url"] = safe_url
templates.env.filters["decimal"] = lambda number: f"{number:.2f}".replace(".", ",")
templates.env.filters["fecha"] = lambda iso: "/".join(reversed(iso[:10].split("-")))


class NotSignedIn(Exception):
    pass


class FromAnotherSite(Exception):
    pass


# --- the API ---


@contextmanager
def backend_client(timeout: float = 10.0) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=BACKEND_URL, timeout=timeout) as client:
        yield client


def call(request: Request, method: str, path: str, *, timeout: float = 10.0, **options) -> httpx.Response:
    """Calls the API on behalf of the visitor: with the session, and with the
    address, which is what the API limits."""
    headers = {"X-Forwarded-For": request.client.host if request.client else ""}
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        headers["Cookie"] = f"{SESSION_COOKIE}={token}"
    with backend_client(timeout=timeout) as client:
        return client.request(method, path, headers=headers, **options)


def call_signed_in(request: Request, method: str, path: str, **options) -> httpx.Response:
    if not request.cookies.get(SESSION_COOKIE):
        raise NotSignedIn
    response = call(request, method, path, **options)
    if response.status_code == 401:
        raise NotSignedIn
    return response


def message_of(response: httpx.Response) -> str:
    """What the API says went wrong, as text."""
    if response.status_code == 429:
        return "Demasiados intentos. Probá de nuevo en un rato."
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    return detail if isinstance(detail, str) else "Revisá los datos: hay alguno que no es válido."


def render(request: Request, template: str, *, status: int = 200, **context) -> HTMLResponse:
    """A page, with the name of the installation and the unread alerts in its heading."""
    context.setdefault("config", _config(request))
    unread = None
    if request.cookies.get(SESSION_COOKIE):
        response = call(request, "GET", "/v1/notificaciones/unread-count")
        unread = response.json()["unread"] if response.status_code == 200 else None
    context |= {"signed_in": unread is not None, "unread": unread}
    return templates.TemplateResponse(request, template, context, status_code=status)


def _config(request: Request) -> dict:
    response = call(request, "GET", "/v1/config")
    return response.json() if response.status_code == 200 else {"nombre": "ContextCrawl", "filtros": []}


# --- requests ---


def _public_url() -> str:
    return os.environ.get("PUBLIC_WEB_URL", "").strip().rstrip("/")


@app.middleware("http")
async def protect(request: Request, call_next) -> Response:
    """Forms sent by other sites are refused, even though the cookie is not sent with them."""
    if request.method not in {"GET", "HEAD", "OPTIONS"} and _from_another_site(request):
        return HTMLResponse("<h1>Solicitud rechazada</h1>", status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer" if request.url.path == "/pausar" else "same-origin")
    return response


def _from_another_site(request: Request) -> bool:
    site = request.headers.get("sec-fetch-site")
    if site is not None and site not in SAME_SITE:
        return True
    origin = request.headers.get("origin")
    if origin is None:
        return False
    if origin == _public_url():
        return False
    return urlsplit(origin).netloc != request.headers.get("host")


@app.exception_handler(NotSignedIn)
def ask_to_sign_in(request: Request, exc: NotSignedIn) -> Response:
    target = request.url.path if request.method == "GET" else "/bandeja"
    response = RedirectResponse(f"/ingresar?{urlencode({'next': target})}", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.exception_handler(httpx.HTTPError)
def backend_down(request: Request, exc: httpx.HTTPError) -> Response:
    message = "El servicio no está disponible en este momento. Probá de nuevo en unos minutos."
    if request.headers.get("hx-request"):  # htmx only shows answers that went well
        return HTMLResponse(f'<p role="alert">{message}</p>')
    return templates.TemplateResponse(
        request,
        "message.html",
        {"config": {"nombre": "ContextCrawl"}, "title": "Servicio no disponible", "message": message},
        status_code=503,
    )


def _inside(target: str) -> str:
    """Where to go after signing in: a page of this site, and nothing else."""
    if target.startswith("/") and not target.startswith(("//", "/\\")) and "\\" not in target:
        return target
    return "/bandeja"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# --- search ---


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return render(request, "search.html")


@app.get("/resultados", response_class=HTMLResponse)
def resultados(
    request: Request,
    q: str,
    date_from: str | None = None,
    date_to: str | None = None,
    mode: str = "semantic",
) -> HTMLResponse:
    params: dict[str, str] = {"q": q, "mode": mode}
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    # Filtros declarados por la instalación (Etapa 1): se reenvían tal
    # cual, sin que la web conozca sus claves de antemano.
    for clave, valor in request.query_params.items():
        if clave.startswith("filtro.") and valor:
            params[clave] = valor

    respuesta = call(request, "GET", "/v1/search", params=params, timeout=30.0)
    if respuesta.status_code != 200:
        mensaje = "Demasiadas búsquedas. Probá de nuevo en un rato." if respuesta.status_code == 429 else message_of(respuesta)
        return templates.TemplateResponse(request, "_error.html", {"message": mensaje})
    return templates.TemplateResponse(
        request, "_resultados.html", {"resultados": respuesta.json()["resultados"], "consulta": q}
    )


@app.post("/valorar", response_class=HTMLResponse)
def valorar(
    request: Request,
    fragmento_id: int = Form(...),
    consulta: str = Form(...),
    valor: str = Form(...),
) -> HTMLResponse:
    respuesta = call(
        request,
        "POST",
        "/v1/valoraciones",
        json={"fragmento_id": fragmento_id, "consulta": consulta, "valor": valor},
    )
    if respuesta.status_code != 201:
        return templates.TemplateResponse(request, "_error.html", {"message": message_of(respuesta)})
    return templates.TemplateResponse(request, "_gracias.html", {"valor": valor})


# --- accounts ---


@app.get("/ingresar", response_class=HTMLResponse)
def sign_in_page(request: Request, next: str = "") -> HTMLResponse:
    return render(request, "account.html", action="/ingresar", next=_inside(next), email="")


@app.get("/registro", response_class=HTMLResponse)
def register_page(request: Request) -> HTMLResponse:
    return render(request, "account.html", action="/registro", next="", email="")


def _sign_in(request: Request, email: str, password: str, target: str) -> Response:
    response = call(request, "POST", "/v1/auth/login", json={"email": email, "password": password})
    if response.status_code != 200:
        return render(
            request, "account.html", status=response.status_code, action="/ingresar", next=target, email=email,
            error=message_of(response),
        )  # fmt: skip
    answer = RedirectResponse(target, status_code=303)
    answer.set_cookie(
        SESSION_COOKIE,
        response.cookies[SESSION_COOKIE],
        max_age=SESSION_SECONDS,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_public_url().startswith("https://"),
    )
    return answer


@app.post("/ingresar")
def sign_in(request: Request, email: str = Form(""), password: str = Form(""), next: str = Form("")) -> Response:
    return _sign_in(request, email, password, _inside(next))


@app.post("/registro")
def register(request: Request, email: str = Form(""), password: str = Form("")) -> Response:
    response = call(request, "POST", "/v1/auth/registro", json={"email": email, "password": password})
    if response.status_code != 201:
        return render(
            request, "account.html", status=response.status_code, action="/registro", next="", email=email,
            error=message_of(response),
        )  # fmt: skip
    return _sign_in(request, email, password, "/bandeja")


@app.post("/salir")
def sign_out(request: Request) -> Response:
    call(request, "POST", "/v1/auth/logout")
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


# --- subscriptions ---


def _subscriptions(request: Request, *, status: int = 200, error: str | None = None) -> HTMLResponse:
    response = call_signed_in(request, "GET", "/v1/suscripciones")
    response.raise_for_status()
    return render(request, "subscriptions.html", status=status, subscriptions=response.json(), error=error)


def _after(request: Request, response: httpx.Response) -> Response:
    if response.is_success:
        return RedirectResponse("/suscripciones", status_code=303)
    return _subscriptions(request, status=response.status_code, error=message_of(response))


@app.get("/suscripciones", response_class=HTMLResponse)
def subscriptions(request: Request) -> HTMLResponse:
    return _subscriptions(request)


async def form_of(request: Request) -> FormData:
    """For the forms whose fields are not known beforehand."""
    return await request.form()


@app.post("/suscripciones")
def create_subscription(request: Request, form: FormData = Depends(form_of)) -> Response:
    text = str(form.get("texto_busqueda", "")).strip()
    filters = {k.removeprefix("filtro."): str(v) for k, v in form.items() if k.startswith("filtro.") and v}
    body = {
        "texto_busqueda": text,
        "filtros": filters,
        "canales": [str(v) for v in form.getlist("canal")],
        "frecuencia_notificacion": str(form.get("frecuencia_notificacion") or "immediate"),
    }
    return _after(request, call_signed_in(request, "POST", "/v1/suscripciones", json=body, timeout=30.0))


@app.post("/suscripciones/{subscription_id}/pausar")
def pause_subscription(request: Request, subscription_id: int) -> Response:
    return _after(request, call_signed_in(request, "POST", f"/v1/suscripciones/{subscription_id}/pausar"))


@app.post("/suscripciones/{subscription_id}/reanudar")
def resume_subscription(request: Request, subscription_id: int) -> Response:
    return _after(request, call_signed_in(request, "POST", f"/v1/suscripciones/{subscription_id}/reanudar"))


@app.post("/suscripciones/{subscription_id}/borrar")
def delete_subscription(request: Request, subscription_id: int) -> Response:
    return _after(request, call_signed_in(request, "DELETE", f"/v1/suscripciones/{subscription_id}"))


@app.post("/suscripciones/{subscription_id}/ajustes")
def change_subscription(request: Request, subscription_id: int, form: FormData = Depends(form_of)) -> Response:
    body = {
        "canales": [str(v) for v in form.getlist("canal")],
        "frecuencia_notificacion": str(form.get("frecuencia_notificacion") or "immediate"),
    }
    return _after(request, call_signed_in(request, "PATCH", f"/v1/suscripciones/{subscription_id}", json=body))


# --- inbox ---


@app.get("/bandeja", response_class=HTMLResponse)
def inbox(request: Request, sin_leer: bool = False, before: int | None = None) -> HTMLResponse:
    params: dict[str, str | int] = {"canal": "bandeja", "limit": PAGE + 1}
    if sin_leer:
        params["unread"] = "true"
    if before is not None:
        params["before"] = before
    response = call_signed_in(request, "GET", "/v1/notificaciones", params=params)
    response.raise_for_status()
    entries = response.json()
    following = None
    if len(entries) > PAGE:
        entries = entries[:PAGE]
        query = {"before": entries[-1]["id"], **({"sin_leer": "1"} if sin_leer else {})}
        following = f"/bandeja?{urlencode(query)}"
    return render(request, "inbox.html", entries=entries, only_unread=sin_leer, following=following)


@app.post("/bandeja/leer-todo")
def read_all(request: Request) -> Response:
    call_signed_in(request, "POST", "/v1/notificaciones/read")
    return RedirectResponse("/bandeja", status_code=303)


@app.post("/bandeja/{entry_id}/leer")
def read_one(request: Request, entry_id: int) -> Response:
    call_signed_in(request, "POST", f"/v1/notificaciones/{entry_id}/read")
    return RedirectResponse("/bandeja", status_code=303)


# --- pausing from an email, without signing in ---


@app.get("/pausar", response_class=HTMLResponse)
def pause_page(request: Request, token: str = "") -> HTMLResponse:
    # Mail scanners open the links of the emails: this only asks.
    return _pause(request, call(request, "GET", "/v1/pause-links", params={"token": token}), token, done=False)


@app.post("/pausar", response_class=HTMLResponse)
def pause(request: Request, token: str = Form("")) -> HTMLResponse:
    return _pause(request, call(request, "POST", "/v1/pause-links", json={"token": token}), token, done=True)


def _pause(request: Request, response: httpx.Response, token: str, *, done: bool) -> HTMLResponse:
    if response.status_code != 200:
        return render(
            request, "message.html", status=response.status_code, title="Pausar suscripción",
            message="El enlace no es válido o venció." if response.status_code == 404 else message_of(response),
        )  # fmt: skip
    return render(request, "pause.html", subscription=response.json(), token=token, done=done)
