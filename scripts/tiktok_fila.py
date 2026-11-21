#!/usr/bin/env python3
"""Fila de postagem TikTok com limite diário e intervalo aleatório (anti-spam). Chamado por: clip tiktok ...

  clip tiktok instalar                 instala o playwright + chromium no ambiente do clipper
  clip tiktok add VIDEO "LEGENDA"
  clip tiktok add-live LIVE            põe na fila todos os cortes da live (legenda = o .txt de cada corte)
  clip tiktok list
  clip tiktok run [--max-dia 5] [--min-min 45] [--max-min 90] [--pausar HORAS] [--dry-run]

Estado em ~/clipper-gta6/tiktok_fila.json. Itens já 'postado' nunca são reenviados.
"""
import argparse, json, random, subprocess, sys, time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from comum import CASA as HOME, CORTES  # noqa: E402
QFILE = HOME / "tiktok_fila.json"


def load():
    if QFILE.exists():
        return json.loads(QFILE.read_text(encoding="utf-8"))
    return {"itens": [], "pausado_ate": None}


def save(q):
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = QFILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(QFILE)  # gravação atômica: queda no meio não corrompe a fila


def postados_hoje(q):
    hoje = datetime.now().date().isoformat()
    return sum(1 for i in q["itens"] if i["estado"] == "postado" and i.get("postado_em", "")[:10] == hoje)


def enviar(item):
    r = subprocess.run([sys.executable, str(HERE / "tiktok_postar.py"), item["video"], item["legenda"]])
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.prog = "clip tiktok"
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("instalar")
    s = sub.add_parser("add"); s.add_argument("video"); s.add_argument("legenda")
    s = sub.add_parser("add-live"); s.add_argument("live")
    sub.add_parser("list")
    r = sub.add_parser("run")
    r.add_argument("--max-dia", type=int, default=5)
    r.add_argument("--min-min", type=int, default=45)
    r.add_argument("--max-min", type=int, default=90)
    r.add_argument("--pausar", type=float, help="congela a fila por N horas (ex.: vídeos travados em 0 views)")
    r.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    q = load()

    if a.cmd == "instalar":
        for cmd in ([sys.executable, "-m", "pip", "install", "-q", "playwright"],
                    [sys.executable, "-m", "playwright", "install", "chromium"]):
            subprocess.run(cmd, check=True)
        print("TikTok pronto. Agora configure CLIPPER_COOKIES_TIKTOK (references/publicar.md).")
    elif a.cmd in ("add", "add-live"):
        if a.cmd == "add":
            pares = [(Path(a.video), a.legenda)]
        else:
            pasta = CORTES / a.live if (CORTES / a.live).is_dir() else \
                next((p for p in sorted(CORTES.glob("*")) if a.live.lower() in p.name), None)
            if not pasta:
                sys.exit(f"não achei cortes de '{a.live}' em {CORTES}")
            pares = [(v, v.with_suffix(".txt").read_text(encoding="utf-8").strip() if v.with_suffix(".txt").exists() else "")
                     for v in sorted(pasta.glob("corte_*.mp4"))]
        for video, legenda in pares:
            if not video.is_file():
                sys.exit(f"arquivo não encontrado: {video}")
            v = str(video.resolve())
            if any(i["video"] == v and i["estado"] != "falhou" for i in q["itens"]):
                print(f"já está na fila: {video.name}")
                continue
            q["itens"].append({"video": v, "legenda": legenda[:2200], "estado": "pendente"})
        save(q); print(f"{sum(i['estado']=='pendente' for i in q['itens'])} pendentes na fila")
    elif a.cmd == "list":
        for n, i in enumerate(q["itens"], 1):
            print(f"{n:02d} [{i['estado']:8}] {Path(i['video']).name}  {i.get('postado_em','')}")
        print(f"hoje: {postados_hoje(q)} postados; pausado_ate={q['pausado_ate']}")
    else:
        if a.min_min > a.max_min:
            sys.exit("--min-min não pode ser maior que --max-min")
        if a.max_dia > 5:
            print("aviso: mais de 5 posts/dia aumenta o risco de shadowban")
        if a.pausar:
            q["pausado_ate"] = (datetime.now() + timedelta(hours=a.pausar)).isoformat(timespec="seconds")
            save(q); print(f"fila pausada até {q['pausado_ate']}"); return
        if q["pausado_ate"] and datetime.fromisoformat(q["pausado_ate"]) > datetime.now():
            sys.exit(f"fila pausada até {q['pausado_ate']}")
        pend = [i for i in q["itens"] if i["estado"] == "pendente"]
        cota = a.max_dia - postados_hoje(q)
        print(f"{len(pend)} pendentes, cota restante hoje: {max(cota,0)}")
        for k, item in enumerate(pend[:max(cota, 0)]):
            if a.dry_run:
                print(f"[dry-run] postaria {Path(item['video']).name} | intervalo antes do próximo: {a.min_min}-{a.max_min} min")
                continue
            ok = enviar(item)
            item["estado"] = "postado" if ok else "falhou"
            if ok:
                item["postado_em"] = datetime.now().isoformat(timespec="seconds")
            save(q)
            print(f"{'postado' if ok else 'FALHOU'}: {Path(item['video']).name}")
            if k < min(len(pend), cota) - 1:
                espera = random.randint(a.min_min, a.max_min)
                print(f"aguardando {espera} min..."); time.sleep(espera * 60)


if __name__ == "__main__":
    main()
