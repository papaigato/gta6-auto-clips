#!/usr/bin/env python3
"""Publica um vídeo no TikTok Studio via Playwright headless, usando cookie de sessão.

Uso: tiktok_postar.py VIDEO "LEGENDA" [--dry-run]
Cookie: arquivo em $CLIPPER_COOKIES_TIKTOK (lista JSON ou formato Netscape) com 'sessionid' de .tiktok.com.
Os seletores dependem da interface do TikTok e podem mudar; em falha, salva screenshot em ~/clipper-gta6/tiktok_debug/.
"""
import argparse, json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import CASA as HOME  # noqa: E402
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
SAMESITE_OK = {"Strict": "Strict", "Lax": "Lax", "None": "None",
               "strict": "Strict", "lax": "Lax", "no_restriction": "None", "unspecified": "Lax"}
UI_BLOCKERS = ["#react-joyride-portal", "[data-test-id='overlay']", ".react-joyride__overlay"]


def ler_cookies(path):
    """Lê JSON (lista) ou Netscape e devolve cookies higienizados (regra 1)."""
    txt = Path(path).read_text(encoding="utf-8").strip()
    if txt.startswith("["):
        brutos = json.loads(txt)
    else:
        brutos = []
        for ln in txt.splitlines():
            if ln.startswith("#HttpOnly_"):
                ln = ln[len("#HttpOnly_"):]
            elif ln.startswith("#") or not ln.strip():
                continue
            p = ln.split("\t")
            if len(p) >= 7:
                brutos.append({"domain": p[0], "path": p[2], "secure": p[3].upper() == "TRUE",
                               "expires": int(p[4] or 0), "name": p[5], "value": p[6]})
    return higienizar(brutos)


def higienizar(brutos):
    limpos = []
    for c in brutos:
        c = {k: v for k, v in c.items() if v is not None}
        for k in ("partitionKey", "storeId", "hostOnly", "session", "id"):
            c.pop(k, None)
        if "expirationDate" in c:
            c["expires"] = int(c.pop("expirationDate"))
        if c.get("expires", 0) in (0, -1):
            c.pop("expires", None)
        ss = SAMESITE_OK.get(c.get("sameSite"))
        if ss:
            c["sameSite"] = ss
        else:
            c.pop("sameSite", None)
        if "name" in c and "value" in c and ("domain" in c or "url" in c):
            limpos.append(c)
    return limpos


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video"); ap.add_argument("legenda")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not Path(a.video).is_file():
        sys.exit(f"vídeo não encontrado: {a.video}")
    ck = os.environ.get("CLIPPER_COOKIES_TIKTOK", "")
    if not ck or not Path(ck).is_file():
        sys.exit("defina CLIPPER_COOKIES_TIKTOK apontando para o arquivo de cookies (veja references/publicar.md)")
    cookies = ler_cookies(ck)
    if not any(c["name"] == "sessionid" for c in cookies):
        sys.exit("cookie 'sessionid' não encontrado no arquivo (sessão expirada ou exportação incompleta)")
    if a.dry_run:
        print(f"[dry-run] {len(cookies)} cookies válidos, sessionid presente (valor não exibido). "
              f"Postaria {Path(a.video).name} com legenda de {len(a.legenda)} caracteres.")
        return

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        sys.exit("falta o playwright: rode 'clip tiktok instalar'")
    dbg = HOME / "tiktok_debug"; dbg.mkdir(parents=True, exist_ok=True)
    etapa = "início"
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True)
        ctx = br.new_context(viewport={"width": 1366, "height": 900})
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        try:
            etapa = "abrir upload"; page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
            etapa = "anexar arquivo (regra 2)"
            for tentativa in range(2):
                try:
                    page.locator('input[type="file"]').first.wait_for(state="attached", timeout=45000)
                    break
                except PWTimeout:
                    if tentativa:
                        raise
                    page.reload(wait_until="domcontentloaded")
            page.locator('input[type="file"]').first.set_input_files(a.video)
            etapa = "remover bloqueios de UI (regra 4)"
            for sel in UI_BLOCKERS:
                page.evaluate("s => document.querySelectorAll(s).forEach(e => e.remove())", sel)
            etapa = "inserir legenda (regra 5)"
            ed = page.locator('[contenteditable="true"]').first
            ed.wait_for(state="visible", timeout=60000)
            ed.click(); page.keyboard.press("ControlOrMeta+A"); page.keyboard.press("Delete")
            ed.type(a.legenda, delay=15)
            etapa = "aguardar processamento (regra 3)"
            btn = page.locator('button[data-e2e="post_video_button"]')
            btn.wait_for(state="attached", timeout=60000)
            for _ in range(180):
                if btn.get_attribute("data-disabled") == "false":
                    break
                time.sleep(2)
            else:
                raise RuntimeError("botão Post não habilitou em 6 min")
            etapa = "clicar em Post (regra 6)"
            page.evaluate("() => document.querySelector('button[data-e2e=\"post_video_button\"]').click()")
            time.sleep(8)
            print("enviado:", Path(a.video).name)
        except Exception as e:
            shot = dbg / f"falha_{int(time.time())}.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
            except Exception:
                pass
            print(f"FALHOU na etapa '{etapa}': {type(e).__name__}. Screenshot: {shot}", file=sys.stderr)
            sys.exit(1)
        finally:
            br.close()


if __name__ == "__main__":
    main()
