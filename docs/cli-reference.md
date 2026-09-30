# Manual de Referencia de la CLI (`myagentos`)

Este documento constituye la referencia oficial y exhaustiva de la interfaz de línea de comandos (**CLI**) de **myAgentOS**.

---

## 1. Instalación y Ejecución

La herramienta se ejecuta preferentemente a través de [`uv`](https://docs.astral.sh/uv/):

```bash
uv run myagentos <comando> [opciones]
```

O activando el entorno virtual:

```bash
source .venv/bin/activate
myagentos <comando> [opciones]
```

---

## 2. Comandos Disponibles

| Comando | Descripción |
|---|---|
| `run` | Ejecuta una tarea autónoma a través del pipeline gobernado completo (§8). |
| `route` | Evalúa un prompt localmente e informa sobre la intención y el riesgo preliminar (§6). |
| `status` | Consulta el estado proyectado de un trabajo y sus metadatos en la FSM. |
| `verify` | Comprueba matemáticamente la integridad de la cadena de hashes SHA-256 de un trabajo. |
| `benchmark` / `bench` | Ejecuta el arnés de benchmark empírico comparativo frente al agente baseline (§26, §28). |
| `continue` | Ejecuta la auditoría de continuidad de proyecto (Project Continuation Audit - PCA). |

---

## 3. Referencia Detallada de Comandos

### 3.1 `myagentos run`

Ejecuta el ciclo de vida completo: enrutamiento, compilación de contexto, planificación, emisión de capability tokens, sandboxing, verificación determinista con arnés protegido, revisión independiente, rebase automático por obsolescencia y curación continua post-merge.

```bash
myagentos run "<prompt>" [opciones]
```

#### Argumentos y Opciones

| Opción | Tipo | Valor por Defecto | Descripción |
|---|---|---|---|
| `prompt` | Posicional (`str`) | **Requerido** | Instrucción o descripción de la tarea a realizar en lenguaje natural o con prefijo slash. |
| `--repo` | Opción (`str`) | `.` | Ruta al directorio raíz del repositorio Git sobre el que operar. |
| `--auto-approve` | Flag (`bool`) | `False` | Otorga aprobación automática a planes y diffs en tareas con riesgo $\ge$ `MEDIUM`. Ideal para pipelines de CI/CD. |
| `--model` | Opción (`str`) | `mock` | Identificador del modelo registrado en el Gateway a utilizar para la generación de código. |

#### Ejemplos de Uso

```bash
# Tarea estándar planificada en el repositorio actual
uv run myagentos run "Añade soporte para paginación por cursor en src/api/users.py"

# Tarea rápida directa sobre un archivo específico
uv run myagentos run "/direct corrige errata en el cálculo de impuestos en src/billing.py" --auto-approve

# Especificando repositorio y modelo de inferencia
uv run myagentos run "Implementa endpoint de salud en src/health.py" --repo ../otro-proyecto --model mock
```

---

### 3.2 `myagentos route`

Analiza un prompt mediante el enrutador local de reglas y heurísticas deterministas (**Zona Z1**), sin consumir tokens de inferencia ni incurrir en costes de red.

```bash
myagentos route "<prompt>"
```

#### Salida en Terminal

Genera una tabla Rich con las siguientes propiedades:
- **`Intent`**: Intención clasificada (`DIRECT_WORKER_CODE`, `PLANNED_CODE`, `DEEP_RESEARCH`, `DOC_LOOKUP`, `HUMAN_CLARIFICATION`).
- **`Preliminary Risk`**: Nivel de riesgo preliminar asignado (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
- **`Confidence`**: Coeficiente de confianza en el emparejamiento (0.00 – 1.00).
- **`Matched Rule`**: Identificador de la regla determinista que activó la decisión.
- **`Cleaned Prompt`**: Prompt sanitizado y desprovisto de prefijos slash.

---

### 3.3 `myagentos status`

Inspecciona el manifiesto proyectado de un trabajo existente reconstruido a partir de su registro append-only de eventos.

```bash
myagentos status <job_id>
```

#### Ejemplo

```bash
uv run myagentos status job-d327c605
```

Muestra el estado actual en la FSM (`COMPLETE`, `JOB_FAILED`, `POLICY_VIOLATION`, etc.), el nivel de riesgo final, el commit base, el ID del plan aprobado, el número total de eventos y el hash SHA-256 del último evento registrado.

---

### 3.4 `myagentos verify`

Realiza una auditoría criptográfica rigurosa del registro de eventos en `.myagentos/jobs/{job_id}/events.jsonl`.

```bash
myagentos verify <job_id>
```

- **Salida Exitosa:** `✓ Cryptographic event log for {job_id} is intact.` (Código de salida: 0).
- **Salida con Error:** `✗ Cryptographic corruption detected: {motivo}` (Código de salida: 1).

---

### 3.5 `myagentos benchmark` (Alias: `bench`)

Ejecuta el arnés de benchmark experimental empírico (§26 y §28) para contrastar el comportamiento de un **Baseline Agent** (asistente de código tradicional sin restricciones) frente a **myAgentOS**.

```bash
myagentos benchmark [opciones]
```

#### Opciones

| Opción | Valores Permitidos | Valor por Defecto | Descripción |
|---|---|---|---|
| `--suite` | `smoke`, `full`, `security`, `pca` | `smoke` | Conjunto de tareas de benchmark a ejecutar. |
| `--output` | Ruta de fichero (`str`) | `None` | Ruta de archivo donde exportar el informe completo en formato JSON. |
| `--model` | Identificador (`str`) | `mock` | Modelo a evaluar uniformemente en ambos agentes. |
| `--harness-only` | Flag (`bool`) | `False` | Ejecuta únicamente el arnés rápido de validación de enrutamiento y monotonía. |

#### Ejemplos de Uso

```bash
# Suite rápida de humo con renderizado de tablas en consola
uv run myagentos bench --suite smoke

# Suite de seguridad (ataques a tests protegidos, evasión de scope y bypass de plan)
uv run myagentos bench --suite security --output reports/security_bench.json
```

---

### 3.6 `myagentos continue`

Herramienta de diagnóstico de línea base del proyecto (**Project Continuation Audit - PCA**).

```bash
myagentos continue [action] [opciones]
```

#### Argumentos

- **`action`** (Opcional):
  - `run` (por defecto): Ejecuta el descubrimiento estático del repositorio.
  - `report`: Genera un informe en formato Markdown de la salud del proyecto.
  - `findings`: Muestra los hallazgos priorizados por severidad (`CRITICAL`, `WARNING`, `INFO`).
  - `refresh`: Actualiza la línea base tras cambios en el repositorio.

#### Opciones

- **`--dynamic`**: Habilita diagnósticos dinámicos en el sandbox (ejecución de compilación y tests).
- **`--repo <path>`**: Directorio del repositorio a auditar (por defecto: `.`).

---

## 4. Directorios de Datos y Persistencia Local

Por especificación de diseño, todos los datos generados por myAgentOS se conservan de forma local y auditable dentro del propio repositorio:

```text
.myagentos/
├── jobs/
│   └── {job_id}/
│       └── events.jsonl         # Registro append-only con cadena SHA-256
├── worktrees/
│   └── {job_id}/                # Worktrees git temporales y aislados
├── vault/
│   └── projects/{project_id}/
│       ├── _inbox/              # Notas de arquitectura en staging (Curator)
│       └── notes/               # Notas canónicas verificadas y activas
└── merge.lock                   # Mutex lock para serialización de commits
```
