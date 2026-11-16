"""One-time setup: connect to the pedal, back up every patch and build its effect catalog.

    python zoom_mcp/setup_pedal.py            # full setup
    python zoom_mcp/setup_pedal.py --refresh  # re-download the FX list and re-read effects
    python zoom_mcp/setup_pedal.py --force    # continue on an untested Zoom model

Nothing is written to the pedal.
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import catalog as C  # noqa: E402
from zoomdev import ZoomDevice  # noqa: E402
from zoompatch import DATA_DIR  # noqa: E402

BACKUP_DIR = os.path.join(HERE, "backups")


def step(msg):
    print(f"\n==> {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="volver a descargar el manual y releer los efectos")
    ap.add_argument("--force", action="store_true", help="continuar aunque el modelo no esté verificado")
    ap.add_argument("--fxlist-url", default=C.FXLIST_URL, help="URL del PDF 'FX list' de Zoom para tu modelo")
    args = ap.parse_args()

    step("Conectando con la pedalera")
    with ZoomDevice() as z:
        info = z.info()
        for k, v in info.items():
            print(f"  {k}: {v}")
        if not z.verified:
            print("\n  AVISO: este modelo no ha sido probado. El formato podría ser distinto y")
            print("  escribir patches podría dañarlos. Solo lectura hasta aquí.")
            if not args.force:
                sys.exit("  Repite con --force si quieres continuar bajo tu propio riesgo.")
        C.save_json("device.json", info)

        step(f"Backup de los {z.num_patches} patches")
        z.edit_mode(True)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = {"model": info["model"], "model_id": z.model_id, "time": stamp, "patches": {}}
        for s in range(z.num_patches):
            _, msg = z.read_slot(s)
            backup["patches"][str(s)] = msg.hex()
        z.edit_mode(False)
        bfile = os.path.join(BACKUP_DIR, f"all-{stamp}.json")
        with open(bfile, "w") as f:
            json.dump(backup, f, indent=1)
        print(f"  guardado en {os.path.relpath(bfile)}")

        ids_path = C.data_path("effects_ids.json")
        if args.refresh or not os.path.exists(ids_path):
            step("Leyendo los efectos instalados en la pedalera (tarda 1-2 minutos)")
            headers = C.read_effect_headers(z)
            C.save_json("effects_ids.json", headers)
        else:
            step("Usando la lista de efectos ya leída (usa --refresh si instalaste efectos nuevos)")
            with open(ids_path, encoding="utf-8") as f:
                headers = json.load(f)
        print(f"  {len(headers)} efectos")

    txt_path = C.data_path("fxlist.txt")
    if args.refresh or not os.path.exists(txt_path):
        step("Descargando la lista oficial de efectos de Zoom")
        text = C.download_fxlist_text(args.fxlist_url)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
    with open(txt_path, encoding="utf-8") as f:
        text = f.read()

    step("Construyendo el catálogo")
    # The original (oldest) backup holds the factory-like values used as defaults.
    first = C.full_backups(BACKUP_DIR)[0]
    with open(first) as f:
        oldest = json.load(f)
    templates = C.build_templates(oldest)
    C.save_json("templates.json", templates)
    parsed = C.parse_fxlist(text, [h["name"] for h in headers])
    cat = C.build_catalog(headers, parsed, templates)
    C.save_json("effects.json", cat)
    unknown = [e["name"] for e in cat if e["params_source"] == "desconocido"]
    print(f"  {len(cat)} efectos en el catálogo, {len(templates)} con valores de fábrica")
    if unknown:
        print(f"  Sin parámetros documentados (se editan como P1, P2...): {', '.join(unknown)}")

    step("Validando: decodificando tus patches con el catálogo")
    total, problems, unk = C.validate(backup, cat)
    print(f"  {total} campos revisados, {len(problems)} fuera de rango")
    for p in problems[:20]:
        print("   -", p)
    if unk:
        print(f"  IDs de efecto no instalados ni catalogados: {', '.join(unk)}")
    with open(C.data_path("validation.txt"), "w", encoding="utf-8") as f:
        f.write(f"{total} campos, {len(problems)} problemas\n" + "\n".join(problems))

    step("Listo")
    print(f"  Datos en {os.path.relpath(DATA_DIR)}  ·  backups en {os.path.relpath(BACKUP_DIR)}")
    print("  Ahora registra el servidor en Claude (ver README).")


if __name__ == "__main__":
    main()
