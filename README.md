# Zoom MCP Server

Servidor [MCP](https://modelcontextprotocol.io) que permite a Claude (u otro cliente MCP) **leer, crear y editar
los patches de una pedalera Zoom G1 FOUR / G1X FOUR** por USB. Pídele a Claude un sonido —
*"un crunch tipo AC/DC con un poco de delay en el slot 12"*— y lo arma y lo guarda en tu pedalera.

> Proyecto no oficial, sin relación con ZOOM Corporation. El protocolo se obtuvo por ingeniería inversa.
> Úsalo bajo tu propio riesgo: el servidor hace backups automáticos, pero no hay garantía.

*English summary at the end.*

---

## Compatibilidad

| | Estado |
|---|---|
| **G1X FOUR**, firmware 2.00 | ✅ Probado (lectura, escritura, vista previa) |
| **G1 FOUR** | 🟡 Debería funcionar (misma familia y protocolo, ID de modelo 0x6E). Sin probar |
| B1 FOUR / B1X FOUR / B2 FOUR | ❔ Protocolo parecido según la comunidad. Solo lectura salvo que se verifique |
| MS-50G/60B/70CDR, G3n/G5n, G6, MS Plus… | ❌ Usan otro protocolo |
| **Windows** | ✅ Probado. Usa la API MIDI nativa, sin dependencias extra |
| **macOS / Linux** | 🟡 Implementado con `python-rtmidi`, sin probar todavía |

Si el servidor detecta un modelo no verificado, **desactiva la escritura** y solo permite leer.

## Requisitos

- Python 3.10 o superior (en macOS/Linux mejor 3.12 o 3.13, para que `python-rtmidi` instale sin compilar)
- La pedalera conectada por USB
- **Zoom Guitar Lab cerrado** mientras uses el servidor: solo un programa puede usar el puerto MIDI a la vez
- Internet la primera vez, para descargar la lista oficial de efectos de Zoom

## Instalación

### 1. Descarga el proyecto e instala las dependencias

```bash
git clone <url-de-este-repo> ZoomMcpServer
cd ZoomMcpServer
python -m venv .venv
```

Activa el entorno: `.venv\Scripts\activate` en Windows o `source .venv/bin/activate` en macOS/Linux. Luego:

```bash
pip install -r requirements.txt
```

### 2. Configura tu pedalera (una sola vez)

Conecta la pedalera, cierra Guitar Lab y ejecuta:

```bash
python zoom_mcp/setup_pedal.py
```

Esto **no escribe nada en la pedalera**. Hace lo siguiente:

1. Detecta el modelo, el firmware y el número de patches.
2. Hace un **backup completo** de tus patches en `zoom_mcp/backups/`.
3. Lee los efectos instalados en *tu* pedalera, con sus IDs internos.
4. Descarga la lista oficial de efectos de Zoom para obtener los parámetros y sus rangos.
5. Construye el catálogo `zoom_mcp/data/effects.json` y lo valida decodificando todos tus patches.

Si después instalas o quitas efectos con Guitar Lab, ejecuta `python zoom_mcp/setup_pedal.py --refresh`.

### 3. Registra el servidor en Claude

Usa **rutas absolutas**: el Python de tu entorno virtual y el `server.py` del proyecto.

**Claude Code:**

```bash
claude mcp add zoom-pedal --scope user -- "C:\ruta\ZoomMcpServer\.venv\Scripts\python.exe" "C:\ruta\ZoomMcpServer\zoom_mcp\server.py"
```

En macOS/Linux el Python está en `.venv/bin/python`. Comprueba que conecta con `claude mcp get zoom-pedal`.

**Claude Desktop**: edita `claude_desktop_config.json`. Está en `%APPDATA%\Claude\` en Windows y en
`~/Library/Application Support/Claude/` en macOS.

```json
{
  "mcpServers": {
    "zoom-pedal": {
      "command": "C:\\ruta\\ZoomMcpServer\\.venv\\Scripts\\python.exe",
      "args": ["C:\\ruta\\ZoomMcpServer\\zoom_mcp\\server.py"]
    }
  }
}
```

Reinicia Claude y abre una conversación nueva: las herramientas se cargan al iniciar.

## Uso

Habla con Claude normalmente. Por ejemplo:

- *"¿Qué patches tengo?"*
- *"Muéstrame qué tiene el patch 12"*
- *"Déjame escuchar un tono limpio tipo surf con chorus y spring reverb, sin guardarlo"*
- *"Guárdalo en el slot 20 con el nombre SurfClean"*
- *"Súbele la ganancia al amp del patch 5 y apaga el delay"*
- *"Restaura el patch 20 como estaba antes"*

### Herramientas

| Herramienta | Qué hace |
|---|---|
| `device_info` | Modelo, firmware, número de patches y estado del catálogo |
| `list_effects` | Efectos instalados con parámetros y rangos (filtra por categoría) |
| `list_patches` | Todos los patches con su cadena de efectos |
| `read_patch` / `read_current_patch` | Detalle de un patch guardado / del que suena ahora |
| `preview_patch` | Carga un sonido para escucharlo **sin guardar** |
| `create_patch` | Crea un patch y lo guarda en un slot |
| `update_patch` | Cambia parámetros, efectos, encendido o nombre de un patch |
| `copy_patch` | Copia un patch a otro slot |
| `select_patch` | Cambia la pedalera a un patch |
| `backup_all` / `list_backups` / `restore_backup` | Copias de seguridad |

### Seguridad y backups

- **Antes de cada escritura** se guarda el contenido anterior del slot en `zoom_mcp/backups/slotNN-<fecha>.json`.
- `setup_pedal.py` y `backup_all` guardan backups completos (`all-<fecha>.json`).
- Para volver atrás, pídele a Claude *"restaura el patch N"* o usa `restore_backup`.
- Los backups y `data/` están en `.gitignore`: son tus patches personales y datos generados.

## Limitaciones conocidas

- **Claude no escucha el sonido.** Elige efectos y valores por conocimiento musical; el ajuste fino lo haces tú, a oído.
- Los tiempos sincronizados al tempo se muestran como `SYNC0`, `SYNC1`…: el número es el índice de la figura
  musical, cuyo valor exacto no está documentado.
- Al guardar, la pedalera reinicia algunos bytes internos del bloque PPRM. No afecta efectos ni nombre.
- Si un efecto no aparece en la lista oficial, sus parámetros se exponen como `P1`, `P2`… con valores crudos.

## Solución de problemas

| Problema | Solución |
|---|---|
| "No se encontró la pedalera Zoom" | Revisa el cable USB y **cierra Guitar Lab**. Si tu puerto MIDI no contiene "ZOOM", define `ZOOM_MIDI_PORT` con parte de su nombre |
| "Falta el catálogo de efectos" | Ejecuta `python zoom_mcp/setup_pedal.py` y reinicia Claude |
| "Escritura desactivada: modelo no verificado" | Tu modelo no está probado. Ver *Añadir soporte para otro modelo* |
| `pip` falla instalando `python-rtmidi` | Usa Python 3.12/3.13, o instala las herramientas de compilación de tu sistema |
| En Windows quieres usar rtmidi | Define `ZOOM_MIDI_BACKEND=rtmidi` |

## Pruebas

```bash
python tests/mcp_client_test.py
```

Arranca el servidor por MCP y llama herramientas de solo lectura.

```bash
python tests/smoke_test.py --write 49
```

Crea y edita un patch en el slot 49 y al final lo restaura.

## Cómo funciona (protocolo)

Verificado en G1X FOUR con firmware 2.00. Todos los mensajes son SysEx `F0 52 00 6E … F7`, con datos empaquetados
8→7 bits: un byte con los bits altos (bit 6 = primer byte) seguido de 7 bytes de datos.

| Comando | Función |
|---|---|
| `F0 7E 00 06 01 F7` | Identificación MIDI universal: modelo y firmware |
| `44` → `43` | Número de patches, tamaño de patch y patches por banco |
| `50` / `51` | Entrar / salir del modo edición |
| `29` → `28` | Leer el patch actual (requiere modo edición) |
| `28 <datos>` | Escribir el patch actual, sin guardar |
| `09 00 <banco> <patch> 00` → `08 …` | Leer un patch de la memoria |
| `08 00 <banco> <patch> <len lo> <len hi> <datos> <crc32 en 5 bytes>` | Guardar un patch en la memoria |
| `60 25/26/27` | Listar archivos de la pedalera |
| `60 20/22/21` | Leer un archivo de la pedalera |

Estructura del patch: `PTCF` con el nombre (10 bytes en 0x1A) y los IDs de los efectos (desde 0x24), seguido de los
bloques `TXJ1` y `TXE1` (descripciones), `EDTB` y `PPRM`. Cada efecto ocupa 24 bytes en `EDTB`, en little-endian:

- bit 0: encendido/apagado
- bits 1–28: ID del efecto
- desde el bit 30: parámetros, los 5 primeros de 12 bits y los siguientes de 8 bits

Los valores crudos son el índice desde el mínimo del rango. Los EQ van en pasos de 0.5 dB.

Los IDs y nombres de los efectos salen del encabezado de cada archivo `.ZD2` de la pedalera. Los parámetros y rangos
salen de la lista oficial de Zoom, con correcciones verificadas en [`overrides.py`](zoom_mcp/overrides.py).

### Estructura del repositorio

```
zoom_mcp/
  server.py        servidor MCP (herramientas)
  setup_pedal.py   configuración inicial: backup + catálogo
  catalog.py       construcción y validación del catálogo
  overrides.py     parámetros verificados a mano
  zoompatch.py     formato de patch y conversión de valores
  zoomdev.py       comandos SysEx de la pedalera
  zfiles.py        lectura de archivos de la pedalera
  midi.py          elige backend MIDI · winmidi.py (Windows) · rtmidi_port.py (macOS/Linux)
  data/            generado por setup_pedal.py (no se sube a git)
  backups/         tus backups (no se sube a git)
tests/
```

### Añadir soporte para otro modelo

1. Ejecuta `python zoom_mcp/setup_pedal.py --force` (solo lee) y revisa que la validación dé 0 errores.
2. Si tu modelo tiene otra lista de efectos, pásala con `--fxlist-url <URL del PDF "FX list" de Zoom>`.
3. Prueba la escritura en un slot que no te importe. Para eso agrega tu ID de modelo a `VERIFIED_MODELS` en
   `zoomdev.py` y ejecuta `tests/smoke_test.py --write <slot>`.
4. Si todo funciona, abre un PR con el modelo y el firmware probados.

## Créditos

- Comandos de archivos y patches basados en [mungewell/zoom-zt2](https://github.com/mungewell/zoom-zt2).
- Parámetros de efectos de la *Effect Types and Parameters* oficial de ZOOM. Se descarga en cada instalación y no
  se redistribuye.

ZOOM, G1 FOUR, G1X FOUR y Guitar Lab son marcas de ZOOM Corporation. Los nombres de modelos de amplificadores
y efectos pertenecen a sus respectivos dueños.

## Licencia

[MIT](LICENSE)

---

## English summary

An MCP server that lets Claude read, create and edit patches on a **Zoom G1 FOUR / G1X FOUR** over USB MIDI.

1. Install the dependencies: `pip install -r requirements.txt`.
2. With the pedal connected and Guitar Lab closed, run `python zoom_mcp/setup_pedal.py`. It backs up your patches
   and builds the effect catalog for your pedal, writing nothing to it.
3. Register `zoom_mcp/server.py` in Claude Code (`claude mcp add`) or Claude Desktop.

Status: tested on Windows with a G1X FOUR on firmware 2.00; macOS/Linux (python-rtmidi) are implemented but untested.
Every write backs up the slot first. Unofficial, reverse-engineered, MIT licensed, no warranty.
