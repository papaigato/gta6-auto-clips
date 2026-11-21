"""Passos 3 e 4: junta as notas que a IA deu, fica com os melhores e monta os cortes verticais.

Cada corte: câmera do streamer em cima, jogo embaixo, título de gancho, legenda palavra por palavra
e um .txt com a legenda do post e as hashtags.
"""
import json
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from comum import (CORTES, YUNET, YUNET_URL, carregar_whisper, gravar_json, hms, ler_json, pasta_temp_live, rodar, segundos,
                   tem_cuda_decode, tem_nvenc, tem_scale_cuda, transcrever_audio, ytdlp)

FONTES = Path(__file__).resolve().parent.parent / "fontes"
OUT_RES = os.environ.get("CLIPPER_OUT_RES", "2k").lower()
if OUT_RES in ("2k", "1440", "1440p", "qhd"):
    L, A = 1440, 2560          # vídeo vertical 2K (9:16)
    CAM_H = 786                # faixa da câmera em cima (30.7% da altura)
else:
    L, A = 1080, 1920          # vídeo vertical Full HD (9:16)
    CAM_H = 590                # faixa da câmera em cima (30.7% da altura)
JOGO_H = A - CAM_H             # faixa do jogo embaixo (69.3% da altura)
PRE_ROLL = 10.0                # baixa 10s antes do corte para garantir keyframe limpo (zero início travado)


# ================================================================ escolher
CHAVES = {"inicio": ("inicio", "início", "start", "comeco", "começo", "de"),
          "fim": ("fim", "end", "final", "ate", "até"),
          "nota": ("nota", "score", "pontos", "pontuacao", "pontuação"),
          "titulo": ("titulo", "título", "title", "gancho", "hook"),
          "post": ("post", "legenda", "caption", "descricao", "descrição")}

LIXO_AUTO = re.compile(
    r"(super\s*chat|mandou\s*(r\$|\d+\s*reais|procurad|vice city)|reais\b|pix\b|doaç[ãa]o|"
    r"obrigad[oa]\s+.*(live|kick|kik|membro|sub|todos voc[êe]s)|se\s+inscrev|deixa\s+o\s+like|"
    r"live\s+na\s+ki[ck]|live\s+todo\s+dia|contagem\s+regressiva|sigam\s+(a[íi]|na)|valeu\s+pelo)", re.I
)


def ler_tolerante(arq):
    """A IA às vezes escreve o JSON com ```json, vírgula sobrando ou comentário. Aceita tudo isso."""
    t = Path(arq).read_text(encoding="utf-8", errors="ignore").strip()
    t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t)
    for tentativa in (t, None):
        if tentativa is None:
            ini = [i for i in (t.find("["), t.find("{")) if i >= 0]
            fim = max(t.rfind("]"), t.rfind("}"))
            if not ini or fim < 0:
                return None
            tentativa = re.sub(r"//[^\n]*", "", t[min(ini):fim + 1])
            tentativa = re.sub(r",\s*([\]}])", r"\1", tentativa)
        try:
            d = json.loads(tentativa)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict):
            d = d.get("momentos") or d.get("cortes") or d.get("moments") or [d]
        return d if isinstance(d, list) else None
    return None


def _campo(m, nome):
    for k in CHAVES[nome]:
        if k in m and m[k] not in (None, ""):
            return m[k]
    return None


def _titulo_auto(pasta, s, e, trans=None):
    if trans is None:
        trans = ler_json(pasta / "transcricao.json", {}).get("segmentos", [])
    falas = [t for a, b, t in trans if s <= a <= e and len(t.split()) >= 3 and not LIXO_AUTO.search(t)]
    if not falas:
        return "OLHA O QUE ACONTECEU NA LIVE"
    t = max(falas, key=lambda x: (x.count("!") * 2 + x.count("?") + len(re.findall(r"[A-ZÁÉÍÓÚÃÕÇ]{3,}", x)), min(len(x), 42)))
    t = re.sub(r"\s+", " ", t).strip(" .,…").upper()
    if len(t) > 42:
        t = t[:42].rsplit(" ", 1)[0].rstrip(" ,.;:-")
        # evita terminar com artigo/preposição solta ("MANDANDO O")
        palavras = t.split()
        while len(palavras) > 3 and palavras[-1] in ("O", "A", "OS", "AS", "DE", "DO", "DA", "E", "QUE", "PRO", "PRA", "UM", "UMA"):
            palavras.pop()
        t = " ".join(palavras)
    return t or "OLHA O QUE ACONTECEU NA LIVE"


def momentos_automaticos(pasta):
    """Sem a IA ter escrito nada: usa os trechos mais quentes (pico de grito/chat), filtrando doação e silêncio inicial."""
    cand = ler_json(pasta / "candidatos.json", [])
    nome = ler_json(pasta / "info.json", {}).get("uploader") or ""
    trans = ler_json(pasta / "transcricao.json", {}).get("segmentos", [])
    out = []
    for c in cand:
        s0, e0 = max(0, c["pico"] - 12), c["pico"] + 32
        falas = [(a, b, t) for a, b, t in trans if s0 <= a <= e0]
        # pula trechos dominados por leitura de super chat / doação / agradecimento
        if falas and sum(1 for _, _, t in falas if LIXO_AUTO.search(t)) >= max(2, len(falas) // 2):
            continue
        # evita começar em silêncio longo: puxa início para a primeira fala real perto do pico
        if falas:
            primeira_fala = falas[0][0]
            if primeira_fala - s0 > 2.5 and e0 - primeira_fala >= 20:
                s0 = max(0.0, primeira_fala - 0.8)
        out.append({"inicio": s0, "fim": e0, "nota": c["calor"], "titulo": _titulo_auto(pasta, s0, e0, trans),
                    "post": f"Olha isso na live {('do ' + nome) if nome else ''} 😳 {HASHTAGS}",
                    "_auto": True})
    return out


PERFIS = {"impacto": (20, 60), "explicativo": (40, 95), "livre": (8, 600)}
PESOS = {"gancho": 0.30, "clareza": 0.20, "contexto": 0.20, "interesse": 0.20, "encerramento": 0.10}
HASHTAGS = os.environ.get("CLIPPER_HASHTAGS", "#gta6 #gtavi #gta #cortes")


def nota_rubrica(criterios):
    """Nota 0-100 pela rubrica ponderada (references/avaliacao.md). None se faltar critério."""
    try:
        return round(10 * sum(p * float(criterios[k]) for k, p in PESOS.items()))
    except (KeyError, TypeError, ValueError):
        return None


def encaixar_em_frases(s, e, segs):
    """Puxa início/fim para o limite de frase mais próximo: nunca começa nem termina no meio de uma fala."""
    if not segs:
        return s, e
    ini = [a for a, _, _ in segs if a <= s + 0.3]
    fim = [b for _, b, _ in segs if b >= e - 0.3]
    s2 = max(ini) if ini and s - max(ini) < 8 else s
    e2 = min(fim) if fim and min(fim) - e < 8 else e
    return max(0.0, s2 - 0.3), e2 + 0.4


def fim_de_frase(t, segs, limite, depois):
    """Fim de frase mais perto de t: o primeiro depois (até `limite`) ou o último antes (a partir de `limite`)."""
    if depois:
        c = [b for _, b, _ in segs if t <= b <= limite]
        return min(c) + 0.4 if c else t
    c = [b for _, b, _ in segs if limite <= b <= t - 0.4]
    return max(c) + 0.4 if c else t


def momentos_de_capitulos(pasta):
    """Capítulos do vídeo viram momentos (perfil livre). Grava momentos/capitulos.json."""
    info = ler_json(pasta / "info.json", {})
    if "chapters" not in info and info.get("url"):  # pasta antiga, sem capítulos salvos: busca de novo
        r = subprocess.run(ytdlp() + ["-J", "--no-playlist", "--no-warnings", info["url"]], capture_output=True, text=True)
        try:
            info["chapters"] = json.loads(r.stdout).get("chapters")
            gravar_json(pasta / "info.json", info)
        except json.JSONDecodeError:
            pass
    caps = [c for c in info.get("chapters") or []
            if c.get("end_time", 0) - c.get("start_time", 0) > 5]
    out = [{"inicio": c["start_time"], "fim": c["end_time"], "nota": 70, "titulo": c.get("title") or f"Parte {i}",
            "post": ""} for i, c in enumerate(caps, 1)]
    if out:
        gravar_json(pasta / "momentos" / "capitulos.json", out)
    return out


def escolher(pasta, manter=3, auto=False, perfil="impacto"):
    minimo, maximo = PERFIS[perfil]
    dur_live = float(ler_json(pasta / "info.json", {}).get("duration") or 10 ** 7)
    segs = ler_json(pasta / "transcricao.json", {}).get("segmentos", [])
    brutos, ruins, avisos = [], [], []
    for arq in sorted((pasta / "momentos").glob("*.json")):
        dados = ler_tolerante(arq)
        if dados is None:
            ruins.append(f"{arq.name}: não é um JSON que dá pra ler")
            continue
        brutos += [(arq.stem, m) for m in dados if isinstance(m, dict)]
    if auto or not brutos:
        if not auto:
            print("A IA não escreveu nenhum momento ainda: usando os trechos mais quentes da live (modo automático).")
        brutos = [("automatico", m) for m in momentos_automaticos(pasta)]
    todos = []
    for origem, m in brutos:
        try:
            s, e = segundos(_campo(m, "inicio")), segundos(_campo(m, "fim"))
        except (TypeError, ValueError, AttributeError):
            ruins.append(f"{origem}: tempo que não entendi em {str(m)[:70]}")
            continue
        if e < s:
            s, e = e, s
        s, e = encaixar_em_frases(max(0.0, s), min(dur_live, e), segs)
        e = min(dur_live, e)
        if e - s < minimo:
            avisos.append(f"[{hms(s)}] tinha {e - s:.0f}s: estiquei pra {minimo}s (perfil {perfil})")
            e = min(dur_live, fim_de_frase(s + minimo, segs, s + maximo, depois=True))
        if e - s > maximo:
            avisos.append(f"[{hms(s)}] tinha {e - s:.0f}s: cortei em {maximo}s (perfil {perfil})")
            e = fim_de_frase(s + maximo, segs, s + minimo, depois=False)
        nota = nota_rubrica(m.get("criterios") or {})
        if nota is None:
            try:
                nota = float(str(_campo(m, "nota") or 70).split("/")[0])
            except ValueError:
                nota = 70.0
        if nota < 60 and origem != "automatico":
            avisos.append(f"[{hms(s)}] nota {nota:.0f} < 60: descartado")
            continue
        titulo = str(_campo(m, "titulo") or "").strip() or _titulo_auto(pasta, s, e, segs)
        post = str(_campo(m, "post") or "").strip()
        if len(re.findall(r"#\w+", post)) < 3:
            post = (post + " " + HASHTAGS).strip()
        todos.append({**m, "titulo": titulo, "post": post, "nota": nota, "_s": s, "_e": e, "_bloco": origem})
    if ruins:
        print("ATENÇÃO, pulei:", *ruins, sep="\n  ")
    if avisos:
        print("Ajustes:", *avisos, sep="\n  ")
    todos.sort(key=lambda m: -m["nota"])
    escolhidos = []
    for m in todos:
        if any(m["_s"] < o["_e"] and o["_s"] < m["_e"] for o in escolhidos):
            continue  # sobrepõe um corte melhor
        escolhidos.append(m)
        if len(escolhidos) >= manter:
            break
    escolhidos.sort(key=lambda m: m["_s"])
    gravar_json(pasta / "escolhidos.json", {"possiveis": len(todos), "perfil": perfil, "cortes": escolhidos})
    print(f"\nAchei {len(todos)} momentos possíveis e fiquei com os {len(escolhidos)} melhores:")
    for i, m in enumerate(escolhidos, 1):
        print(f"  {i}. [{hms(m['_s'])}–{hms(m['_e'])}] nota {m['nota']:.0f}  {m.get('titulo', '')}")
    if len(escolhidos) < manter:
        print(f"  (só {len(escolhidos)} bons: não invente momento pra completar)")
    return escolhidos


# ================================================================ câmera do streamer
def dimensoes_video(video):
    """Lê largura e altura reais do vídeo rapidamente via ffprobe."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height", "-of", "csv=s=x:p=0", str(video)],
            capture_output=True, text=True, timeout=15
        )
        partes = r.stdout.strip().splitlines()[0].split("x")
        w, h = int(partes[0]), int(partes[1])
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    return 1920, 1080


def duracao_video(video, padrao=45.0):
    """Lê duração do vídeo com fallback seguro (nunca quebra em float(''))."""
    for cmd in (
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration", "-of", "csv=p=0", str(video)],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            txt = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
            if txt and txt.upper() != "N/A":
                val = float(txt)
                if val > 0.5:
                    return val
        except Exception:
            pass
    return float(padrao)


def achar_camera(video):
    """Procura o rosto em 14 quadros do trecho e devolve a caixa (x, y, l, a) do rosto mais frequente."""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(video))
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if W <= 0 or H <= 0:
        cap.release()
        W, H = dimensoes_video(video)
        return W, H, None
    if not YUNET.exists():
        YUNET.parent.mkdir(parents=True, exist_ok=True)
        try:
            import urllib.request
            urllib.request.urlretrieve(YUNET_URL, str(YUNET))
        except Exception:
            pass
    if not YUNET.exists():
        cap.release()
        return W, H, None
    dur_ms = duracao_video(video, padrao=30.0) * 1000
    esc = 960 / W
    h_esc = max(1, int(H * esc))
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (960, h_esc), 0.65)
    caixas = []
    for k in range(14):
        cap.set(cv2.CAP_PROP_POS_MSEC, dur_ms * (k + 0.5) / 14)
        ok, q = cap.read()
        if not ok:
            continue
        _, rostos = det.detect(cv2.resize(q, (960, h_esc)))
        for r in rostos if rostos is not None else []:
            if r[14] >= 0.65 and r[3] / esc > H * 0.04:
                caixas.append([v / esc for v in r[:4]])
    cap.release()
    if len(caixas) < 3:
        return W, H, None
    c = np.array(caixas)
    centros = c[:, :2] + c[:, 2:] / 2
    med = np.median(centros, axis=0)
    perto = c[np.linalg.norm(centros - med, axis=1) < W * 0.08]
    if len(perto) < 3:
        return W, H, None
    rosto = np.median(perto, axis=0)
    if rosto[3] > H * 0.30:  # rosto muito grande (>30% da tela) = podcast / live só de câmera
        return W, H, None
    return W, H, [float(v) for v in rosto]


ESTILOS = ("auto", "split", "blur", "preencher")


def ler_visual(pasta):
    """Visual da live: visual.json (gravado pelo clip.py) ou, se não houver, as variáveis CLIPPER_ESTILO/FOCO."""
    v = ler_json(pasta / "visual.json") or {}
    estilo = str(v.get("estilo") or os.environ.get("CLIPPER_ESTILO", "auto")).lower()
    try:
        foco = min(max(float(v.get("foco", os.environ.get("CLIPPER_FOCO", 0.5))), 0.0), 1.0)
    except (TypeError, ValueError):
        foco = 0.5
    return {"estilo": estilo if estilo in ESTILOS else "auto", "foco": foco}


def obter_camera_live(pasta, trecho, estilo):
    """Detecta a câmera uma vez por live (camera.json). Sem rosto achado, cai para fundo desfocado."""
    W, H = dimensoes_video(trecho)
    if estilo in ("blur", "preencher"):
        print(f"      estilo: {estilo}", flush=True)
        return W, H, None
    cam = ler_json(pasta / "camera.json")
    if cam and cam.get("W") == W and cam.get("H") == H and cam.get("rosto") is not None:
        return W, H, cam["rosto"]
    print("      procurando a câmera do streamer (1x por live)…", flush=True)
    W_det, H_det, rosto = achar_camera(trecho)
    W, H = (W_det or W), (H_det or H)
    if rosto is not None:
        print("      câmera achada: câmera em cima, jogo embaixo", flush=True)
        gravar_json(pasta / "camera.json", {"W": W, "H": H, "rosto": rosto})
    else:
        print("      não achei câmera do streamer: jogo inteiro com fundo desfocado", flush=True)
    return W, H, rosto


def _par(v):
    return int(v) // 2 * 2


def caixa_camera(W, H, rosto):
    """Recorte da webcam. Padrão: centrado no rosto com folga no topo (sem cortar testa/fone) e ombros."""
    fx, fy, fw, fh = rosto
    fcx, fcy = fx + fw / 2, fy + fh / 2
    if os.environ.get("CLIPPER_CAM_MODO", "rosto").lower() == "canto":
        cw = _par(0.246 * W)
        ch = _par(cw * CAM_H / L)
        cx = 0.012 * W if fcx < W / 2 else W - 0.012 * W - cw
        cy = 0.022 * H if fcy < H / 2 else H - 0.022 * H - ch
    else:
        cw = _par(min(max(fw * 3.8, 0.14 * W), 0.48 * W))
        ch = _par(cw * CAM_H / L)
        cx, cy = fcx - cw / 2, fcy - 0.50 * ch
    cx = _par(min(max(cx, 0), W - cw))
    cy = _par(min(max(cy, 0), H - ch))
    return cw, ch, cx, cy


def _filtro_escala(w, h, usa_scale_cuda=False):
    if usa_scale_cuda:
        return f"format=nv12,hwupload_cuda,scale_cuda={w}:{h},hwdownload,format=nv12"
    return f"scale={w}:{h}:flags=bilinear"


def filtro(W, H, rosto, dur=None, estilo="auto", foco=0.5, fade=0.3, trim_s=0.0, usa_scale_cuda=False):
    """Monta o filtro de vídeo em 2K/1080p: trim+setpts zera PTS (zero travamento inicial + banner garantido)."""
    leg = "ass=legenda.ass:fontsdir=fontes"
    fd = ""
    if dur and fade > 0:
        f = min(fade, dur / 4)
        fd = f",fade=t=in:st=0:d={f:.2f},fade=t=out:st={max(dur - f, 0):.2f}:d={f:.2f}"
    base = (f"[0:v]trim=start={trim_s:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS"
            if dur else "[0:v]setpts=PTS-STARTPTS")
    if estilo == "preencher":
        return (f"{base},scale={L}:{A}:force_original_aspect_ratio=increase:flags=bilinear,"
                f"crop={L}:{A}:(iw-ow)*{min(max(foco, 0), 1)}:(ih-oh)/2,setsar=1,format=yuv420p,{leg}{fd}[v]")
    if rosto is None or estilo == "blur":
        # fundo: desfoca em 1/4 da resolução e amplia (mesmo visual, bem mais leve)
        esc_bg = _filtro_escala(L, A, usa_scale_cuda)
        return (f"{base},split=2[vbg][vfg];"
                f"[vbg]scale={L // 4}:{A // 4}:force_original_aspect_ratio=increase:flags=bilinear,"
                f"crop={L // 4}:{A // 4},boxblur=8:2,{esc_bg}[bg];"
                f"[vfg]scale={L}:-2:flags=bilinear[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p,{leg}{fd}[v]")
    cw, ch, cx, cy = caixa_camera(W, H, rosto)
    gw = _par(min(W, H * L / JOGO_H))
    gx = _par((W - gw) / 2)
    esc_cam = _filtro_escala(L, CAM_H, usa_scale_cuda)
    esc_jogo = _filtro_escala(L, JOGO_H, usa_scale_cuda)
    return (f"{base},split=2[vcam][vjog];"
            f"[vcam]crop={cw}:{ch}:{cx}:{cy},{esc_cam},setsar=1[cam];"
            f"[vjog]crop={gw}:{H}:{gx}:0,{esc_jogo},setsar=1[jogo];"
            f"[cam][jogo]vstack=inputs=2,format=yuv420p,{leg}{fd}[v]")


def tem_audio(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                        "-of", "csv=p=0", str(video)], capture_output=True, text=True)
    return bool(r.stdout.strip())


def primeiro_pts_video(video):
    """Retorna o timestamp (s) do primeiro quadro de vídeo válido (detecta atraso de keyframe no stream copy)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-read_intervals", "%+#1",
             "-show_entries", "frame=best_effort_timestamp_time", "-of", "csv=p=0", str(video)],
            capture_output=True, text=True, timeout=15
        )
        for linha in r.stdout.splitlines():
            t = linha.strip()
            if t and t != "N/A":
                return max(0.0, float(t))
    except Exception:
        pass
    return 0.0


# ================================================================ legenda
def _ass_tempo(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _limpo(txt):
    return txt.replace("{", "(").replace("}", ")").replace("\\", "/").strip()


def audio_16k(arquivo, inicio=0.0, duracao=None):
    """O ffmpeg lê o áudio exato do corte (sincronizado com o trim/pre-roll do vídeo)."""
    import numpy as np
    seek_in = max(0.0, inicio - 4.0)
    trim_s = max(0.0, inicio - seek_in)
    cmd = ["ffmpeg", "-v", "error"]
    if seek_in > 0:
        cmd += ["-ss", f"{seek_in:.3f}"]
    cmd += ["-i", str(arquivo)]
    if trim_s > 0:
        cmd += ["-ss", f"{trim_s:.3f}"]
    if duracao:
        cmd += ["-t", f"{duracao:.3f}"]
    cmd += ["-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    r = subprocess.run(cmd, capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768


def palavras_do_trecho(video, idioma, modelo="small", inicio=0.0, duracao=None):
    """Palavras com tempo (pra legenda palavra por palavra). Se a GPU falhar, passa pra CPU e fica nela."""
    audio = audio_16k(video, inicio=inicio, duracao=duracao)
    try:
        segs, _ = transcrever_audio(carregar_whisper(modelo), audio, idioma, palavras=True)
    except RuntimeError as e:
        if "cublas" not in str(e).lower() and "cuda" not in str(e).lower():
            raise
        os.environ.update(CLIPPER_DEVICE="cpu", CLIPPER_COMPUTE_TYPE="int8")
        segs, _ = transcrever_audio(carregar_whisper(modelo), audio, idioma, palavras=True)
    return [(w.start, w.end, w.word.strip()) for sg in segs for w in (sg.words or []) if w.word.strip()]


def quebrar_titulo_banner(titulo, max_carac=24):
    palavras = titulo.split()
    linhas, atual = [], []
    tam = 0
    for p in palavras:
        if tam + len(p) + (1 if atual else 0) > max_carac and atual:
            linhas.append(" ".join(atual))
            atual = [p]
            tam = len(p)
        else:
            atual.append(p)
            tam += len(p) + (1 if len(atual) > 1 else 0)
    if atual:
        linhas.append(" ".join(atual))
    return r"\N".join(linhas)


def _agrupar_palavras(palavras, max_palavras=3, max_pausa=0.55):
    """Agrupa até 3 palavras por legenda, SEMPRE quebrando quando há pausa/silêncio (evita legenda congelada)."""
    grupos, atual = [], []
    for item in palavras:
        if atual and (len(atual) >= max_palavras or (item[0] - atual[-1][1]) > max_pausa):
            grupos.append(atual)
            atual = [item]
        else:
            atual.append(item)
    if atual:
        grupos.append(atual)
    return grupos


def escrever_ass(caminho, titulo, palavras, dur, com_camera):
    esc = A / 1920.0
    cx = L // 2
    y_titulo = int(CAM_H + 0.055 * A) if com_camera else int(A * 0.25)
    y_leg = int(A * 0.74)  # zona segura acima da interface do TikTok/Reels/Shorts
    fs_gancho = int(round(48 * esc))
    out_gancho = int(round(20 * esc))
    fs_leg = int(round(68 * esc))
    out_leg = int(round(8 * esc))
    sh_leg = int(round(2 * esc))
    marg = int(round(45 * esc))
    titulo_formatado = quebrar_titulo_banner(_limpo(titulo).upper())
    dur_gancho = min(3.8, dur)
    mostrar_banner = os.environ.get("CLIPPER_BANNER", "1") != "0" and bool(titulo_formatado)
    linhas = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {L}", f"PlayResY: {A}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        f"Style: Gancho,Montserrat ExtraBold,{fs_gancho},&H00FFFFFF,&H00FFFFFF,&H000808D0,&H000808D0,-1,0,0,0,100,100,0,0,3,{out_gancho},0,5,{marg},{marg},0,1",
        f"Style: Leg,Montserrat ExtraBold,{fs_leg},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{out_leg},{sh_leg},2,{marg},{marg},0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if mostrar_banner:
        linhas.append(
            f"Dialogue: 1,0:00:00.00,{_ass_tempo(dur_gancho)},Gancho,,0,0,0,,{{\\fad(120,300)\\pos({cx},{y_titulo})}}{titulo_formatado}"
        )
    grupos = _agrupar_palavras(palavras, max_palavras=3, max_pausa=0.55)
    for g, grupo in enumerate(grupos):
        prox = grupos[g + 1][0][0] if g + 1 < len(grupos) else dur
        for k, (s, e, _) in enumerate(grupo):
            if k + 1 < len(grupo):
                fim = min(grupo[k + 1][0], e + 0.45)
            else:
                fim = prox if (prox - e) < 0.45 else min(dur, e + 0.28)
            fim = min(dur, max(s + 0.12, fim))
            txt = " ".join(("{\\c&H0020FFFF&}" if j == k else "{\\c&HFFFFFF&}") + _limpo(w).upper()
                           for j, (_, _, w) in enumerate(grupo))
            linhas.append(f"Dialogue: 0,{_ass_tempo(s)},{_ass_tempo(fim)},Leg,,0,0,0,,{{\\pos({cx},{y_leg})}}{txt}")
    Path(caminho).write_text("\n".join(linhas) + "\n", encoding="utf-8")


# ================================================================ baixar só o pedaço
def formato_download():
    """Prioriza VP9/H.264 (decodificados por hardware na GPU T4) evitando AV1 pesado na CPU."""
    max_h = os.environ.get("CLIPPER_MAX_RES", "1440")
    return f"bv*[height<={max_h}][vcodec!*=av01]+ba/bv*[height<={max_h}]+ba/b[height<={max_h}]/best"


def tem_video(arq):
    """Checagem ultra-rápida (~0.05s) de integridade do vídeo via cabeçalho ffprobe."""
    p = Path(arq)
    if not p.exists() or p.stat().st_size < 50_000:
        return False
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_type", "-of", "csv=p=0", str(p)],
            capture_output=True, text=True, timeout=15
        )
        return "video" in r.stdout.lower()
    except Exception:
        return p.stat().st_size > 100_000


_UA_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def baixar_trecho(pasta, url, s, e, destino, silencioso=False):
    """Baixa com pre-roll de 10s (evita os 3s travados por falta de keyframe no início!) em stream copy rápido."""
    max_h = os.environ.get("CLIPPER_MAX_RES", "1440")
    s_dl = max(0.0, s - PRE_ROLL)
    e_dl = e + 1.5
    pre = s - s_dl
    if not silencioso:
        print(f"      baixando pedaço em {max_h}p60 (VP9/H264 + pre-roll anti-travamento)…", flush=True)
    fmt = formato_download()
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        rodar(ytdlp() + ["-f", fmt, "--no-playlist", "--no-warnings", "-q", "--download-sections",
                         f"*{s_dl:.2f}-{e_dl:.2f}", "--merge-output-format", "mkv",
                         "-o", str(destino), url], timeout=900)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    if destino.exists() and tem_video(destino):
        return destino, pre
    for ext in ("mkv", "webm", "mp4", "part"):
        for cand in (destino.with_suffix(f".{ext}"), destino.parent / f"{destino.name}.{ext}"):
            if cand != destino and cand.exists() and tem_video(cand):
                cand.replace(destino)
                return destino, pre
    destino.unlink(missing_ok=True)
    if not silencioso:
        print("      tentando de outro jeito (pulando direto pro minuto do corte)…", flush=True)
    r = subprocess.run(ytdlp() + ["-f", fmt, "-g", "--no-playlist", "--no-warnings", url],
                       capture_output=True, text=True)
    links = [l for l in r.stdout.split() if l.startswith("http")]
    if links:
        entrada = []
        for l in links[:2]:
            entrada += ["-user_agent", _UA_CHROME, "-ss", f"{s_dl:.2f}", "-i", l]
        mapa = ["-map", "0:v:0", "-map", f"{len(links[:2]) - 1}:a:0?"]
        try:
            rodar(["ffmpeg", "-y", "-loglevel", "error", *entrada, "-t", f"{e_dl - s_dl:.2f}", *mapa,
                   "-c", "copy", str(destino)], timeout=900)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
    if destino.exists() and tem_video(destino):
        return destino, pre
    destino.unlink(missing_ok=True)
    raise SystemExit("NÃO CONSEGUI BAIXAR esse pedaço do vídeo. Rode 'instalar' (atualiza o baixador) e depois "
                     "'fazer' de novo: os cortes que já ficaram prontos não são refeitos.")


def _args_encoder():
    """NVENC (GPU NVIDIA) otimizado em -preset p2, senão libx264."""
    q = os.environ.get("CLIPPER_CRF", "18")
    if tem_nvenc():
        return ["-c:v", "h264_nvenc", "-preset", "p2", "-rc", "vbr", "-cq", q, "-b:v", "0", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", q, "-pix_fmt", "yuv420p"]


def fps_saida(video):
    """Respeita CLIPPER_FPS (30 ou 60); em auto usa 60 fps quando a fonte tem 50+."""
    pref = os.environ.get("CLIPPER_FPS", "auto").lower().strip()
    if pref in ("30", "60"):
        return int(pref)
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate",
                        "-of", "csv=p=0", str(video)], capture_output=True, text=True)
    try:
        n, d = (r.stdout.strip().splitlines()[0].split("/") + ["1"])[:2]
        return 60 if float(n) / float(d or 1) >= 50 else 30
    except (ValueError, IndexError, ZeroDivisionError):
        return 30


# ================================================================ fazer
def fazer(pasta, modelo_legenda="small"):
    info = ler_json(pasta / "info.json", {})
    escolhidos = ler_json(pasta / "escolhidos.json", {}).get("cortes")
    if not escolhidos:
        raise SystemExit("Nenhum corte escolhido ainda. Rode antes: clip.py escolher " + pasta.name)
    idioma = ler_json(pasta / "transcricao.json", {}).get("idioma")
    destino = CORTES / pasta.name
    destino.mkdir(parents=True, exist_ok=True)
    temp_base = pasta_temp_live(pasta)
    usa_nvenc = tem_nvenc()
    usa_hwdec = tem_cuda_decode()
    usa_scale_cuda = tem_scale_cuda()
    enc_args = _args_encoder()
    forcar = os.environ.get("CLIPPER_FORCAR_REFAZER", "0") == "1"
    visual = ler_visual(pasta)
    estilo, foco = visual["estilo"], visual["foco"]
    fade = float(os.environ.get("CLIPPER_FADE", "0.3"))
    fps_env = os.environ.get("CLIPPER_FPS", "auto").lower()
    paralelo = max(1, int(os.environ.get("CLIPPER_PARALELO", "2" if usa_nvenc else "1")))

    def _assinatura(item):
        return f"v3-{L}x{A}-{fps_env}-{item['_s']:.2f}-{item['_e']:.2f}-{item.get('titulo', '')}-{estilo}-{foco}"

    modo_gpu = (
        f"GPU NVIDIA NVENC{' + NVDEC' if usa_hwdec else ''}{' + scale_cuda' if usa_scale_cuda else ''}"
        if usa_nvenc else "CPU (libx264)"
    )
    print(f"      [Turbo {L}x{A}] {modo_gpu} | Paralelo: {paralelo}x | Temp: {temp_base}", flush=True)

    def _precisa_fazer(idx, item):
        saida_ = destino / f"corte_{idx:02d}.mp4"
        if forcar or not saida_.exists():
            return True
        for arq in (destino / f".corte_{idx:02d}.assin", pasta / f"corte_{idx:02d}" / "feito.txt"):
            if arq.exists():
                return arq.read_text(encoding="utf-8") != _assinatura(item)
        return True

    def _preparar_trecho(idx, item, silencioso=False):
        s_, e_ = item["_s"], item["_e"]
        tdir_t = temp_base / f"corte_{idx:02d}"
        tdir_t.mkdir(parents=True, exist_ok=True)
        trecho_ = tdir_t / "trecho.mkv"
        de_txt = tdir_t / "de.txt"
        chave = f"pre{PRE_ROLL:.1f}-{s_:.2f}-{e_:.2f}"
        pre_ = min(PRE_ROLL, s_)
        if forcar:
            trecho_.unlink(missing_ok=True)
            de_txt.unlink(missing_ok=True)
        if de_txt.exists() and de_txt.read_text() != chave:
            trecho_.unlink(missing_ok=True)
        if trecho_.exists() and not tem_video(trecho_):
            trecho_.unlink(missing_ok=True)
        if not trecho_.exists():
            trecho_, pre_ = baixar_trecho(pasta, info["url"], s_, e_, trecho_, silencioso=silencioso)
            de_txt.write_text(chave)
        return trecho_, pre_

    whisper_lock = threading.Lock()
    cam_lock = threading.Lock()

    def _processar_corte(idx, m, trecho_pre=None):
        s, e = m["_s"], m["_e"]
        print(f"\n[4/4] Corte {idx}/{len(escolhidos)}: {m.get('titulo', '')}  ({hms(s)}–{hms(e)})", flush=True)
        tdir_cache = pasta / f"corte_{idx:02d}"
        tdir_cache.mkdir(exist_ok=True)
        tdir_tmp = temp_base / f"corte_{idx:02d}"
        tdir_tmp.mkdir(parents=True, exist_ok=True)
        saida = destino / f"corte_{idx:02d}.mp4"
        assinatura = _assinatura(m)

        if trecho_pre is not None:
            trecho, pre = trecho_pre
        else:
            trecho, pre = _preparar_trecho(idx, m, silencioso=(paralelo > 1))

        dur_arq = duracao_video(trecho, padrao=max(10.0, (e - s) + pre))
        v_pts0 = primeiro_pts_video(trecho)
        # Pula o pre-roll e qualquer atraso inicial de keyframe (zero vídeo travado nos primeiros segundos!)
        offset = max(pre, v_pts0 + 0.25)
        if dur_arq > 8.0 and offset > dur_arq - 8.0:
            offset = min(max(v_pts0 + 0.25, 0.0), max(0.0, dur_arq - 8.0))
        dur = min(max(8.0, e - s), max(5.0, dur_arq - offset))

        with cam_lock:
            W, H, rosto = obter_camera_live(pasta, trecho, estilo)

        with whisper_lock:
            palavras = palavras_do_trecho(trecho, idioma, modelo_legenda, inicio=offset, duracao=dur)

        escrever_ass(tdir_tmp / "legenda.ass", m.get("titulo", ""), palavras, dur, rosto is not None)
        (tdir_tmp / "fontes").mkdir(exist_ok=True)
        for fonte in FONTES.glob("*.ttf"):
            dest_f = tdir_tmp / "fontes" / fonte.name
            if not dest_f.exists():
                shutil.copy(fonte, dest_f)

        saida_render = (tdir_tmp / f"render_{idx:02d}.mp4") if temp_base != pasta else saida
        fps = fps_saida(trecho)
        seek_in = max(0.0, offset - 4.0)
        trim_s = max(0.0, offset - seek_in)
        print(f"      [Corte {idx:02d}] renderizando {L}x{A}@{fps}fps ({'GPU' if usa_nvenc else 'CPU'})…", flush=True)

        fc_base = filtro(W, H, rosto, dur, estilo, foco, fade, trim_s=trim_s, usa_scale_cuda=usa_scale_cuda)
        mapa_a = ["-map", "0:a?"]
        if tem_audio(trecho):
            f = min(fade, dur / 4)
            afade = (f",afade=t=in:st=0:d={f:.2f},afade=t=out:st={max(dur - f, 0):.2f}:d={f:.2f}" if f > 0 else "")
            fc_base += f";[0:a]atrim=start={trim_s:.3f}:duration={dur:.3f},asetpts=PTS-STARTPTS,aresample=44100{afade}[a]"
            mapa_a = ["-map", "[a]"]

        def _rodar_ffmpeg(hwdec_on, scale_cuda_on):
            fc = fc_base if scale_cuda_on == usa_scale_cuda else (
                filtro(W, H, rosto, dur, estilo, foco, fade, trim_s=trim_s, usa_scale_cuda=scale_cuda_on)
                + (fc_base[fc_base.index(";[0:a]"):] if ";[0:a]" in fc_base else "")
            )
            cmd = ["ffmpeg", "-y", "-loglevel", "error"]
            if hwdec_on:
                cmd += ["-hwaccel", "cuda"]
            if seek_in > 0:
                cmd += ["-ss", f"{seek_in:.3f}"]
            cmd += ["-i", trecho.name, "-filter_complex", fc, "-map", "[v]", *mapa_a, *enc_args,
                    "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                    str(saida_render.resolve())]
            rodar(cmd, cwd=tdir_tmp)

        try:
            _rodar_ffmpeg(usa_hwdec, usa_scale_cuda)
        except subprocess.CalledProcessError:
            # Fallback seguro se o stream tiver codec não suportado pelo NVDEC (ex.: AV1 na T4)
            _rodar_ffmpeg(False, False)

        if saida_render != saida:
            shutil.copy2(saida_render, saida)
        post = (f"{m.get('titulo', '')}\n\n{m.get('post', '').strip()}\n\n"
                f"Corte de {info.get('uploader') or info.get('channel')}: {info.get('webpage_url') or info['url']}\n")
        saida.with_suffix(".txt").write_text(post, encoding="utf-8")
        (tdir_cache / "feito.txt").write_text(assinatura, encoding="utf-8")
        (destino / f".corte_{idx:02d}.assin").write_text(assinatura, encoding="utf-8")
        print(f"      PRONTO [Corte {idx:02d}]: {saida}", flush=True)
        if tdir_tmp != tdir_cache:
            shutil.rmtree(tdir_tmp, ignore_errors=True)
        return saida

    pendentes = []
    feitos = []
    for i, m in enumerate(escolhidos, 1):
        saida = destino / f"corte_{i:02d}.mp4"
        if not _precisa_fazer(i, m):
            print(f"\n[4/4] Corte {i}/{len(escolhidos)}: já estava pronto", flush=True)
            feitos.append(saida)
        else:
            pendentes.append((i, m))

    if pendentes:
        # Primeiro corte detecta a câmera (1x por live) e já aquece o Whisper na GPU
        primeiro_idx, primeiro_m = pendentes[0]
        feitos.append(_processar_corte(primeiro_idx, primeiro_m))
        restantes = pendentes[1:]
        if restantes:
            if paralelo > 1:
                with ThreadPoolExecutor(max_workers=paralelo) as pool:
                    futs = [pool.submit(_processar_corte, idx, item) for idx, item in restantes]
                    for fut in futs:
                        feitos.append(fut.result())
            else:
                for idx, item in restantes:
                    feitos.append(_processar_corte(idx, item))

    nomes = {f.stem for f in feitos}
    for velho in [*destino.glob("corte_*.*"), *destino.glob(".corte_*.assin")]:  # sobras de uma escolha anterior
        if velho.name.lstrip(".").split(".")[0] not in nomes:
            velho.unlink(missing_ok=True)
    print(f"\n{len(feitos)} cortes prontos em {L}x{A} pra postar em {destino}")
    return feitos
