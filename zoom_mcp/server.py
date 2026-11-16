"""MCP server for Zoom G1 FOUR / G1X FOUR multi-effects pedals (USB MIDI / SysEx).

Tools let an assistant list, read, create and edit patches on the pedal.
Every write first saves the previous content of the slot to ./backups.
Run setup_pedal.py once before using it (builds data/effects.json for your pedal).
"""
import json
import os
import struct
import sys
import time
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mcp.server.mcpserver import MCPServer  # noqa: E402

from catalog import full_backups  # noqa: E402
from zoomdev import ZoomDevice, MidiError, unpack7  # noqa: E402
from zoompatch import Patch, load_catalog, load_templates, value_to_raw, describe_param  # noqa: E402

FX_PER_PATCH = 5
BACKUP_DIR = os.path.join(HERE, "backups")
CATALOG = load_catalog()
BY_NAME = {e["name"].upper(): e for e in CATALOG.values()}
TEMPLATES = load_templates()
SETUP_HINT = ("Falta el catálogo de efectos. Ejecuta una vez: python zoom_mcp/setup_pedal.py "
              "(con la pedalera conectada) y reinicia el servidor.")

mcp = MCPServer(
    "zoom-pedal",
    instructions=(
        "Controla una pedalera Zoom (G1 FOUR / G1X FOUR) conectada por USB. Usa device_info para saber "
        "cuántos patches tiene (normalmente 0-49, bancos de 10). Cada patch tiene hasta 5 efectos en "
        "cadena (slot 1 = primero). Usa list_effects para ver los efectos instalados y sus parámetros "
        "antes de crear patches. Usa preview_patch para que el usuario escuche un patch sin guardarlo, y "
        "create_patch / update_patch para guardarlo. Cada escritura hace backup automático del slot. "
        "Zoom Guitar Lab debe estar cerrado mientras se usa este servidor."
    ),
)


# ---------------------------------------------------------------- helpers
def _need_catalog():
    if not CATALOG:
        raise RuntimeError(SETUP_HINT)


def _check_slot(slot: int):
    if slot < 0:
        raise ValueError("slot no puede ser negativo")  # upper bound is checked by the device


def _find_effect(name: str) -> dict:
    e = BY_NAME.get(name.strip().upper())
    if e:
        return e
    cands = [v for k, v in BY_NAME.items() if name.strip().upper().replace(" ", "") in k.replace(" ", "")]
    if len(cands) == 1:
        return cands[0]
    hint = f" ¿Quisiste decir: {', '.join(c['name'] for c in cands)}?" if cands else ""
    raise ValueError(f"Efecto '{name}' no está instalado en la pedalera.{hint} Usa list_effects.")


def _backup_slot(slot: int, data: bytes, reason: str) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    fn = os.path.join(BACKUP_DIR, f"slot{slot:02d}-{stamp}.json")
    with open(fn, "w") as f:
        json.dump({"slot": slot, "time": stamp, "reason": reason, "name": Patch(data).name, "data": data.hex()}, f)
    return os.path.basename(fn)


def _store(z: ZoomDevice, slot: int, data: bytes) -> None:
    if not z.verified:
        raise MidiError(f"Escritura desactivada: el modelo {z.model_name} no está verificado.")
    z.write_slot(slot, data)


def _apply_effect(p: Patch, idx: int, spec: dict, base_raw=None):
    """spec = {"effect": name, "on": bool, "params": {name: value}}; idx is 0-based."""
    if not spec or str(spec.get("effect", "")).strip().lower() in ("", "none", "vacio", "vacío", "empty"):
        p.set_effect(idx, 0, False, [0] * 9)
        return
    info = _find_effect(spec["effect"])
    if base_raw is not None:                       # editing an existing effect: keep its values
        raw = (list(base_raw) + [0] * 9)[:9]
    elif info["id"] in TEMPLATES:                  # factory values (also fills hidden fields)
        raw = (list(TEMPLATES[info["id"]]) + [0] * 9)[:9]
    else:                                          # never seen: middle of each range
        raw = [0] * 9
        for i, prm in enumerate(info["params"]):
            if "enum" not in prm:
                mid = 0 if prm["min"] < 0 < prm["max"] else (prm["min"] + prm["max"]) // 2
                raw[i] = value_to_raw(prm, mid)
        if info["category"] == "AMP":
            raw[7] = 2  # hidden field present in every factory amp
    names = {prm["name"].upper(): i for i, prm in enumerate(info["params"])}
    for k, v in (spec.get("params") or {}).items():
        i = names.get(str(k).upper())
        if i is None:
            raise ValueError(f"{info['name']} no tiene parámetro '{k}'. Parámetros: {[q['name'] for q in info['params']]}")
        raw[i] = value_to_raw(info["params"][i], v)
    p.set_effect(idx, info["id"], spec.get("on", True), raw)


def _patch_view(p: Patch) -> dict:
    return p.to_dict(CATALOG)


def _out(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- tools
@mcp.tool()
def device_info() -> str:
    """Verifica la conexión con la pedalera y devuelve modelo, firmware y número de patches."""
    with ZoomDevice() as z:
        info = z.info()
    info.update({"efectos_por_patch": FX_PER_PATCH, "efectos_en_catalogo": len(CATALOG),
                 "escritura_habilitada": info["verified_model"]})
    if not CATALOG:
        info["aviso"] = SETUP_HINT
    return _out(info)


@mcp.tool()
def list_effects(category: str = "") -> str:
    """Lista los efectos instalados en la pedalera con sus parámetros y rangos.

    category: filtra por DYNAMICS, FILTER, DRIVE, AMP, CABINET, MODULATION, SFX, DELAY, REVERB o PEDAL.
    Valores 'SYNCn' en tiempos/velocidades = sincronizado al tempo (n = índice de figura musical).
    """
    _need_catalog()
    out = {}
    for e in sorted(CATALOG.values(), key=lambda e: e["id"]):
        if category and e["category"].upper() != category.strip().upper():
            continue
        out.setdefault(e["category"], []).append({
            "name": e["name"], "description": e.get("description", ""),
            "params": {p["name"]: describe_param(p) for p in e["params"]}})
    return _out(out)


@mcp.tool()
def list_patches() -> str:
    """Lista todos los patches (normalmente 0-49) con su nombre y la cadena de efectos."""
    res = []
    with ZoomDevice() as z:
        for s in range(z.num_patches):
            data, _ = z.read_slot(s)
            p = Patch(data)
            chain = []
            for i in range(p.num_effects):
                e = p.effect(i)
                if e["id"]:
                    nm = CATALOG.get(e["id"], {}).get("name", f"?{e['id']:#x}")
                    chain.append(nm if e["on"] else f"({nm} off)")
            res.append(f"{s:02d}  {p.name:<10}  " + " > ".join(chain))
    return "\n".join(res)


@mcp.tool()
def read_patch(slot: int) -> str:
    """Muestra en detalle un patch guardado (slot 0-49): efectos, encendido/apagado y parámetros."""
    _check_slot(slot)
    with ZoomDevice() as z:
        data, _ = z.read_slot(slot)
    return _out({"slot": slot, **_patch_view(Patch(data))})


@mcp.tool()
def read_current_patch() -> str:
    """Muestra el patch que está sonando ahora en la pedalera (incluye cambios no guardados)."""
    with ZoomDevice() as z:
        z.edit_mode(True)
        data = z.read_current()
    return _out(_patch_view(Patch(data)))


def _build(slot_data: bytes, name: str, effects: list, description: str) -> Patch:
    _need_catalog()
    if len(effects) > FX_PER_PATCH:
        raise ValueError(f"Máximo {FX_PER_PATCH} efectos por patch")
    p = Patch(slot_data)
    if name:
        p.name = name
    for i in range(FX_PER_PATCH):
        _apply_effect(p, i, effects[i] if i < len(effects) else None)
    if description:
        p.set_description(description)
    return p


@mcp.tool()
def create_patch(slot: int, name: str, effects: list[dict], description: str = "") -> str:
    """Crea un patch nuevo y lo GUARDA en el slot indicado (0-49), reemplazando lo que había.

    name: hasta 10 caracteres.
    effects: lista de hasta 5 efectos en orden de la cadena, cada uno:
      {"effect": "TS Drive", "on": true, "params": {"Gain": 60, "Tone": 55, "VOL": 80}}
      Parámetros omitidos toman valores por defecto. Usa list_effects para nombres y rangos.
    description: texto opcional (se muestra en Guitar Lab).
    Antes de escribir se guarda un backup del slot.
    """
    _check_slot(slot)
    with ZoomDevice() as z:
        z.edit_mode(True)
        old, _ = z.read_slot(slot)
        p = _build(old, name, effects, description)
        bk = _backup_slot(slot, old, "create_patch")
        _store(z, slot, p.bytes())
        back, _ = z.read_slot(slot)
        z.program_change(slot)
    v = _patch_view(Patch(back))
    return _out({"ok": True, "slot": slot, "backup": bk, "guardado": v,
                 "nota": "Patch seleccionado en la pedalera para que lo escuches."})


@mcp.tool()
def preview_patch(name: str, effects: list[dict]) -> str:
    """Carga un patch en la pedalera para ESCUCHARLO SIN GUARDAR (se pierde al cambiar de patch).

    Mismo formato de effects que create_patch.
    """
    with ZoomDevice() as z:
        z.edit_mode(True)
        cur = z.read_current()
        p = _build(cur, name, effects, "")
        z.write_current(p.bytes())
        time.sleep(0.3)
        back = z.read_current()
    return _out({"ok": True, "sonando_ahora": _patch_view(Patch(back))})


@mcp.tool()
def update_patch(slot: int, effect_slot: int = 0, effect: str = "", on: bool | None = None,
                 params: dict | None = None, name: str = "") -> str:
    """Modifica un patch guardado sin rehacerlo entero y lo guarda.

    effect_slot: posición 1-5 del efecto a modificar (0 = no tocar efectos, p.ej. solo renombrar).
    effect: si se indica, reemplaza el efecto de esa posición por otro ("none" para vaciarla).
    on: encender/apagar el efecto. params: {"Gain": 70, ...} solo los que cambian.
    name: nuevo nombre del patch (opcional).
    """
    _check_slot(slot)
    with ZoomDevice() as z:
        z.edit_mode(True)
        old, _ = z.read_slot(slot)
        p = Patch(old)
        if name:
            p.name = name
        if effect_slot:
            _need_catalog()
            if not 1 <= effect_slot <= FX_PER_PATCH:
                raise ValueError("effect_slot debe ser 1-5")
            i = effect_slot - 1
            cur = p.effect(i)
            if effect:
                _apply_effect(p, i, {"effect": effect, "on": True if on is None else on, "params": params})
            else:
                if cur["id"] == 0:
                    raise ValueError(f"La posición {effect_slot} está vacía; indica 'effect'.")
                info = CATALOG.get(cur["id"])
                if info is None and params:
                    raise ValueError("Efecto desconocido; no se pueden editar sus parámetros.")
                spec = {"effect": info["name"], "on": cur["on"] if on is None else on, "params": params}
                _apply_effect(p, i, spec, base_raw=cur["raw_params"])
        bk = _backup_slot(slot, old, "update_patch")
        _store(z, slot, p.bytes())
        back, _ = z.read_slot(slot)
        z.program_change(slot)
    return _out({"ok": True, "slot": slot, "backup": bk, "guardado": _patch_view(Patch(back))})


@mcp.tool()
def copy_patch(from_slot: int, to_slot: int, new_name: str = "") -> str:
    """Copia un patch de un slot a otro (con nombre nuevo opcional)."""
    _check_slot(from_slot)
    _check_slot(to_slot)
    with ZoomDevice() as z:
        z.edit_mode(True)
        src, _ = z.read_slot(from_slot)
        old, _ = z.read_slot(to_slot)
        p = Patch(src)
        if new_name:
            p.name = new_name
        bk = _backup_slot(to_slot, old, f"copy_patch from {from_slot}")
        _store(z, to_slot, p.bytes())
    return _out({"ok": True, "copiado": f"{from_slot} -> {to_slot}", "nombre": p.name, "backup": bk})


@mcp.tool()
def select_patch(slot: int) -> str:
    """Cambia la pedalera al patch indicado (0-49) para escucharlo."""
    _check_slot(slot)
    with ZoomDevice() as z:
        z.program_change(slot)
    return f"Patch {slot} seleccionado."


@mcp.tool()
def backup_all() -> str:
    """Guarda una copia de seguridad completa de todos los patches en la carpeta backups."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    with ZoomDevice() as z:
        out = {"model": z.model_name, "model_id": z.model_id, "time": stamp, "patches": {}}
        z.edit_mode(True)
        for s in range(z.num_patches):
            _, msg = z.read_slot(s)
            out["patches"][str(s)] = msg.hex()
    fn = os.path.join(BACKUP_DIR, f"all-{stamp}.json")
    with open(fn, "w") as f:
        json.dump(out, f, indent=1)
    return f"Backup completo guardado: backups/{os.path.basename(fn)}"


@mcp.tool()
def list_backups(slot: int = -1) -> str:
    """Lista los backups disponibles (de un slot, o todos si slot = -1)."""
    if not os.path.isdir(BACKUP_DIR):
        return "No hay backups."
    rows = []
    if slot == -1:
        rows += [f"{os.path.basename(f)}  (completo)" for f in full_backups(BACKUP_DIR)]
    for fn in sorted(os.listdir(BACKUP_DIR)):
        if fn.startswith("slot"):
            s = int(fn[4:6])
            if slot in (-1, s):
                with open(os.path.join(BACKUP_DIR, fn)) as f:
                    d = json.load(f)
                rows.append(f"{fn}  slot {s}  '{d['name']}'  ({d['reason']})")
    return "\n".join(rows) or "No hay backups."


@mcp.tool()
def restore_backup(backup_file: str, slot: int = -1) -> str:
    """Restaura un patch desde un backup.

    backup_file: nombre de archivo de list_backups.
    - Backup de un slot (slotXX-...): se restaura en su slot original (o en 'slot' si se indica).
    - Backup completo (all-...): indica 'slot' para restaurar ese patch; slot=-1 restaura TODOS.
    """
    path = os.path.join(BACKUP_DIR, os.path.basename(backup_file))
    with open(path) as f:
        d = json.load(f)
    todo = {}
    if "data" in d:
        todo[d["slot"] if slot == -1 else slot] = bytes.fromhex(d["data"])
    else:
        keys = sorted(map(int, d["patches"])) if slot == -1 else [slot]
        for s in keys:
            m = bytes.fromhex(d["patches"][str(s)])
            todo[s] = unpack7(m[10:-6])[:m[8] | m[9] << 7]
    done = []
    with ZoomDevice() as z:
        z.edit_mode(True)
        for s, data in todo.items():
            _check_slot(s)
            old, _ = z.read_slot(s)
            _backup_slot(s, old, f"antes de restaurar {os.path.basename(path)}")
            _store(z, s, data)
            done.append(f"{s:02d} {Patch(data).name}")
    return "Restaurado:\n" + "\n".join(done)


if __name__ == "__main__":
    mcp.run()
