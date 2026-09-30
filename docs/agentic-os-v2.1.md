# Agentic OS: Arquitectura de Sistema y Especificación Técnica

**Versión:** 2.1 — consolidación tras auditoría de coherencia
**Fecha:** 2026-09-30
**Estado:** Propuesta técnica / no implementar sin validación experimental (el harness de benchmark forma parte de P0, §28)

Documento de diseño y especificación de arquitectura para un sistema operativo agéntico (*Agentic OS*) orientado al desarrollo de software: optimización del consumo de tokens, ejecución aislada y gobernada, orquestación de modelos por roles y control explícito de permisos, coste, evidencia y riesgo.

> **Nota de alcance:** este documento define la arquitectura y los contratos del sistema. Las cifras de latencia, coste, ahorro de tokens, umbrales y tasas de regresión son **objetivos o valores por defecto** hasta que se validen mediante benchmark reproducible (§26).

> **Convenciones:** el texto es normativo y está escrito en presente. "Debe" y "no debe" son obligaciones; "puede" es opcional. Cada regla tiene **un único lugar normativo**; el resto de secciones la referencian. El historial de cambios y el estado de actualidad de proveedores viven en el Apéndice A.

---

## 1. Resumen Ejecutivo y Objetivos de Diseño

El propósito del sistema es sustituir el flujo habitual de desarrollo asistido por IA —volcado masivo de archivos en contexto, razonamiento no restringido y correcciones ciegas en bucle— por una arquitectura distribuida, trazable y gobernada por **riesgo, permisos, coste y evidencia**.

### Principios de diseño

```text
┌────────────────────────────────────────────────────────────────────────┐
│                         PRINCIPIOS DE DISEÑO                           │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Local-First Routing: el routing primario no requiere un LLM remoto. │
│ 2. Capability Least Privilege: cada worker recibe permisos explícitos. │
│ 3. Deterministic Verification: tests y tooling validan resultados.     │
│ 4. Isolated Execution: el código generado corre en un entorno efímero. │
│ 5. Risk-Based Approval: la aprobación depende del riesgo (§5), no solo │
│    de la complejidad.                                                  │
│ 6. Evidence-First Research: toda afirmación externa conserva fuente,   │
│    versión, fecha y hash de contenido (obligatorio).                   │
│ 7. Provider-Agnostic Models: los modelos se eligen por rol, capacidad, │
│    política, coste y disponibilidad; no por un escalón fijo.           │
│ 8. Trust Tagging: todo contenido lleva una etiqueta de confianza que   │
│    los contenidos derivados heredan.                                   │
│ 9. Autoridad determinista: el LLM propone; el Job Controller y el      │
│    Policy Engine deciden.                                              │
└────────────────────────────────────────────────────────────────────────┘
```

### Objetivos no funcionales

- Reducir contexto irrelevante sin sacrificar el contexto necesario para la tarea.
- Evitar que el agente tenga autoridad implícita sobre todo el repositorio.
- Evitar que una prueba o un arnés modificado por el mismo agente sea tomado como verificación independiente.
- Evitar que un resultado se integre en la rama activa del usuario sin que la política de riesgo lo permita.
- Separar **plano de control**, **acceso a modelos**, **research** y **ejecución de código**.
- Poder reconstruir una ejecución completa a posteriori (§24, §25).
- Ser resistente a retiradas, cambios de precio y cambios de proveedor.

---

## 2. Topología de Despliegue y Supuestos

Para que las garantías de atomicidad, presupuesto y serialización tengan sentido, se declara la topología objetivo:

- **Demonio local mono-usuario** (`agenticd`) por estación de trabajo. La CLI, la TUI y los plugins de IDE son clientes del demonio.
- **Un Job Controller por repositorio.** Los jobs de un mismo repositorio pueden ejecutarse en paralelo en worktrees distintos; **los merges se serializan** con un lock por repositorio (§16).
- **Persistencia:**
  - `events.jsonl` por job: log append-only con cadena de hashes. Es la **fuente de verdad**; el estado del job (`manifest.json`) es una proyección regenerable (§24).
  - Un store transaccional local (SQLite en modo WAL o equivalente) para presupuesto, reservas y cuotas. La reserva atómica de presupuesto (§17) es una transacción sobre este store.
- **Fuera de alcance de esta versión:** despliegue multiusuario o remoto. Requeriría un store central para presupuesto y cuotas, y autenticación entre cliente y demonio.
- **Implementación de referencia asumida:** Python 3.12+ (asyncio, pydantic, Textual/Rich, tree-sitter, onnxruntime, Trafilatura). Los contratos (esquemas, eventos, tokens) son independientes del lenguaje.
- **Runtime de contenedores:** Docker rootless o Podman rootless; runtimes de aislamiento reforzado (gVisor, Kata, Firecracker) para riesgo alto (§11).

---

## 3. Glosario y Nomenclatura

Cada término designa un único componente. No existen sinónimos.

| Término | Naturaleza | Definición |
|---|---|---|
| **Job Controller** | determinista, sin LLM | Único componente que decide transiciones de la FSM y persiste el estado. |
| **Local Router** | local (ONNX/reglas) | Clasifica la petición y emite `{intent, preliminary_risk, confidence}` (§6). No es una frontera de seguridad. |
| **Context Compiler** | local, determinista | Construye `PLAN_CONTEXT` y `WORKER_CONTEXT` (§9). |
| **Policy Engine** | determinista | Componente único de política: emite capability tokens, calcula el riesgo final, valida el PatchSet y el diff, evalúa constraints de ADR. "Policy Validation" es la **fase** de la FSM en que se invoca. |
| **Planner** | LLM | Genera el `PLAN_SPEC`. |
| **Worker** | LLM (llamada única o bucle acotado) | Propone ediciones y `tool_calls`. Corre en el plano de control; no tiene shell ni acceso directo al filesystem (§10). |
| **Test Author** | LLM, rol distinto del Worker | Escribe los tests de aceptación a partir del `PLAN_SPEC` (§13). |
| **Tool Broker** | determinista | Ejecuta las herramientas pedidas por el Worker, tras validarlas contra el capability token. |
| **Code Sandbox** | contenedor / microVM | Único lugar donde corre código generado o comandos del proyecto. Sin red por defecto (§11). |
| **Verification Guard** | determinista | Ejecuta el pipeline de verificación con arnés y tests protegidos (§13). |
| **Independent Reviewer** | reglas + LLM | Revisión independiente del diff (§15). Un modelo distinto del que generó el cambio. |
| **Failure Classifier** | determinista | Clasifica fallos con un enum cerrado (§14). |
| **Model Gateway** | determinista | Único componente con egreso hacia proveedores de modelos. Incluye el **Resource Governor** (presupuesto, cuotas, circuit breaker) (§17). |
| **Curator** | LLM económico / gratuito | Redacta notas de conocimiento (propósito, decisiones, lecciones) en staging post-merge (§7, §22). No accede al razonamiento del worker ni escribe en canónicas. |
| **Audit Trail** | registro | Log reproducible del job (§24, §25). No es una fase de la FSM. |

El término "Orchestrator" no se usa: el Planner es el LLM que planifica y el Job Controller es el componente determinista que gobierna el flujo.

---

## 4. Diagrama de Arquitectura Global

```text
                  [ Usuario / CLI / IDE ]
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                      Job Controller                     │
│         FSM determinista + Event Store (sin LLM)        │
└─────────────────────────────────────────────────────────┘
                             │
         ┌───────────────────┬───────────────────┐
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   Local Router  │ │ Context Compiler│ │  Policy Engine  │
│    ONNX / CPU   │ │Tree-sitter / MCP│ │   Capabilities  │
└─────────────────┘ └─────────────────┘ └─────────────────┘
         │                   │                   │
         └───────────────────┬───────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────┐
│      Model Gateway · único egreso hacia proveedores     │
│    Registry · RPM/TPM · presupuesto · circuit breaker   │
└─────────────────────────────────────────────────────────┘
                             │ Planner / Worker / Test Author / Reviewer (LLM)
                             ▼
┌─────────────────────────────────────────────────────────┐
│                      Planner (LLM)                      │
│ genera PLAN_SPEC · riesgo final lo fija el Policy Engine│
└─────────────────────────────────────────────────────────┘
                             │ aprobación según riesgo
                             ▼
┌─────────────────────────────────────────────────────────┐
│       Git worktree efímero (rama agentic/<job_id>)      │
└─────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│      Worker (LLM) — propone ediciones y tool_calls      │
└─────────────────────────────────────────────────────────┘
                             │ tool_calls
                             ▼
┌─────────────────────────────────────────────────────────┐
│         Tool Broker — aplica el capability token        │
└─────────────────────────────────────────────────────────┘
                             │ comandos permitidos
                             ▼
┌─────────────────────────────────────────────────────────┐
│            Code Sandbox — sin red por defecto           │
└─────────────────────────────────────────────────────────┘
                             │ PatchSet (hashes estampados por el controlador)
                             ▼
┌─────────────────────────────────────────────────────────┐
│            Policy Validation (Policy Engine)            │
└─────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                    Verification Guard                   │
│  compile · lint · tests protegidos · tests del proyecto │
└─────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                    Independent Review                   │
│      determinista + LLM independiente según riesgo      │
└─────────────────────────────────────────────────────────┘
                             │ HIGH / CRITICAL
                             ▼
┌─────────────────────────────────────────────────────────┐
│                Aprobación humana del diff               │
└─────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│    Merge Controller → commit en rama agentic/<job_id>   │
└─────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│     KNOWLEDGE_UPDATE (post-merge, no bloqueante)        │
│   Context Compiler (hechos) + Curator (prosa) → staging │
└─────────────────────────────────────────────────────────┘
                             │
                             ▼
                          COMPLETE
```

Ramas de fallo (ver §8 y §14): cualquier fallo de Policy Validation, Verification Guard o Independent Review pasa por el **Failure Classifier**, que decide `RETRY`, `CONTEXT_EXPANSION`, `ENV_REPAIR`, `ESCALATED` o `STOP` según una tabla cerrada. Tras el merge, `KNOWLEDGE_UPDATE` es estrictamente no bloqueante: su fallo o timeout se audita pero nunca revierte el merge ni impide pasar a `COMPLETE`.

### Zonas de red

La red **no se deshabilita globalmente**. Se distinguen cinco zonas:

```text
Z1. Control Plane
    Job Controller, Router, Context Compiler, Policy Engine, Tool Broker,
    stores. SIN egreso directo a Internet.

Z2. Model Gateway
    Único componente con salida hacia proveedores de modelos
    (allowlist de FQDN de proveedores).

Z3. Research Plane
    Salida a Internet controlada: fetchers aislados detrás de un proxy de
    egreso con allowlist (§21).

Z4. Code Sandbox
    SIN red por defecto (--network none). Modos alternativos en §11.

Z5. Host / Workspace del usuario
    Nunca se entrega directamente al código generado.
```

El objetivo no es impedir que el sistema agéntico use Internet, sino impedir que **el código generado tenga acceso arbitrario a Internet o a secretos del host**. Docker documenta que `--network none` aísla completamente la pila de red del contenedor, dejando únicamente loopback ([referencia](https://docs.docker.com/engine/network/drivers/none/)).

---

## 5. Modelo de Riesgo

El riesgo es una propiedad del **cambio real**, no solo del texto de la petición.

### 5.1 Niveles y fases

Niveles: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.

| Fase | Quién | Entrada | Uso |
|---|---|---|---|
| Riesgo preliminar | Local Router | prompt, slash commands, heurísticas, mapa estructural | Elegir el camino inicial (§6) |
| Riesgo final (`RISK_FINAL`) | Policy Engine | scope propuesto en el plan: rutas, tipo de cambio | Fijar aprobaciones y perfil de ejecución |
| Riesgo del diff (`RISK_DIFF`) | Policy Engine | PatchSet real | Confirmar o elevar el riesgo tras generar |

**Regla monótona:** dentro de un job el riesgo solo puede **subir**. Si sube después de una aprobación, esa aprobación deja de ser válida y el job vuelve a `WAIT_PLAN_APPROVAL` o pasa por `WAIT_DIFF_APPROVAL` según corresponda (§8).

### 5.2 Señales de riesgo

El Policy Engine eleva el nivel cuando el scope o el diff tocan cualquiera de:

```text
auth / autorización / sesiones
bases de datos, esquemas, migraciones
infraestructura, despliegue, Dockerfile, Makefile
.github/workflows/*, CI/CD
secretos, credenciales, configuración de entorno
manifiestos y lockfiles de dependencias, scripts de build/install
API pública (firmas exportadas)
configuración de hooks, linters, arnés de tests
tests protegidos (§13)
```

### 5.3 Matriz de controles por riesgo

Valores por defecto configurables por proyecto; ninguno puede ser "sin tope".

| Control | LOW | MEDIUM | HIGH | CRITICAL |
|---|---|---|---|---|
| **Criterio de entrada** | ≤3 archivos, ≤150 líneas de diff, sin señales de §5.2 | >3 archivos o cambios de firma interna | Cualquier señal de §5.2 (auth, DB, infra, API pública, dependencias) | Secretos, CI/CD, permisos, migraciones destructivas, borrado o cambio de tests protegidos |
| **Aprobación del plan** | Automática por política (micro-plan registrado) | Usuario | Usuario | Usuario con confirmación reforzada |
| **Aprobación de datos** | Según clasificación (§18), independiente del riesgo | ← | ← | ← |
| **Aprobación del diff** | No | Opcional (por defecto no) | Sí | Sí |
| **Perfil de Code Sandbox** | Endurecido estándar | Endurecido estándar | Aislamiento reforzado (gVisor/Kata) | microVM (Firecracker o equivalente) |
| **Independent Review** | Solo determinista | + LLM de modelo distinto | + LLM de proveedor distinto si existe | Ídem + revisión humana obligatoria |
| **Rol mínimo del Worker** | `worker_economy` | `worker_economy` | `worker_strong` | `worker_strong` |
| **Intentos máx. por job** | 3 | 4 | 4 | 2 |
| **Destino del commit** | Rama de job; integración automática solo si `auto_integrate: true` | Rama de job; integra el usuario | Rama de job; integra el usuario | Rama de job; integra el usuario |

Los topes de USD y de tiempo de reloj por job son obligatorios y se definen por proyecto (§14, §17).

### 5.4 Ruta rápida (`DIRECT_WORKER_CODE`)

La ruta rápida **no salta la gobernanza**; usa una versión ligera de la misma:

1. Se genera un **micro-plan** (archivos, operación, test a ejecutar) sin coste de Planner: lo produce el Context Compiler y lo valida el Policy Engine.
2. El capability token de la ruta rápida es restrictivo: `max_files`, `max_diff_lines`, sin rutas sensibles (§5.2) y sin permisos de red.
3. Si el Worker intenta salirse del token, o `RISK_FINAL`/`RISK_DIFF` supera `LOW`, el job se **reescala** a `PLAN_SPEC` completo. El reescalado no consume intentos.

Así un *false-direct* del router no es un fallo de seguridad, sino un coste de reescalado.

---

## 6. Capa de Enrutamiento: Local Router

El router procesa la petición localmente antes de abrir cualquier conexión con un proveedor de modelos.

### Propiedades

- **Motor:** ONNX Runtime con un modelo de embeddings ligero y/o clasificador local, más reglas.
- **Coste remoto:** 0 tokens de API para el routing.
- **Latencia:** objetivo `p95 < 20 ms`, pendiente de benchmark por plataforma.
- **Memoria:** objetivo configurable; no se garantiza `<100 MB` sin benchmark de la combinación modelo/runtime/plataforma.
- **Entrada:** no depende exclusivamente del embedding del prompt completo.
- **Salida:** `{intent, preliminary_risk, confidence}`.

### Routing híbrido

```text
Prompt
  │
  ├─ Regla explícita / slash command ──► match directo
  │
  ├─ Heurísticas de riesgo ──► elevación de preliminary_risk
  │
  ├─ Clasificador / embedding local ──► intent + confidence
  │
  └─ Confianza insuficiente ──► ABSTAIN
```

### Intenciones y su rama en la FSM

Cada intención tiene una transición definida en §8:

| Intención | Descripción | Rama FSM |
|---|---|---|
| `DIRECT_WORKER_CODE` | Tarea mecánica de bajo riesgo y alcance acotado | Ruta rápida (§5.4) |
| `PLANNED_CODE` | Multiarchivo, estructural o riesgo ≥ MEDIUM | Ruta completa con PLAN_SPEC |
| `DEEP_RESEARCH` | Investigación técnica externa | `RESEARCH_RUN` (§21) |
| `DOC_LOOKUP` | Recuperación de conocimiento del proyecto | `DOC_LOOKUP_RUN` (§22) |
| `ABSTAIN` | Sin confianza suficiente | Según `abstain_action` |

`abstain_action` es configurable: `PLAN` (por defecto; ruta completa con suelo de riesgo `MEDIUM`) o `ASK_USER` (pide aclaración al usuario). Nunca se degrada a ruta rápida.

### Regla de seguridad

El error de routing con mayor coste es el **false-direct**. Preferimos enrutar de más hacia planificación. **El router no es una frontera de seguridad**: solo elige el camino inicial. La seguridad la imponen `RISK_FINAL`, `RISK_DIFF` y los capability tokens.

```yaml
routing:
  direct_worker_min_confidence: 0.92
  planned_min_confidence: 0.80
  abstain_action: PLAN
  otherwise: ABSTAIN
```

Los umbrales son parámetros a calibrar con datos reales, no valores universales. Se miden `false-direct rate` y tasa de reescalado (§26).

---

## 7. Roles de Modelo y Model Registry

El sistema **no fija modelos concretos ni escalones de calidad**. Define **roles** con capacidades requeridas; el registry resuelve qué modelo cumple cada rol en cada momento.

### Roles lógicos

| Rol | Responsabilidad | Capacidades requeridas | Despliegue |
|---|---|---|---|
| `router` | Routing local | intent classification / embeddings | `local` |
| `worker_economy` | Generación de código, extracción, reparación de tests | code_generation, structured_output | `remote` |
| `worker_strong` | Fallback y debugging difícil | razonamiento de código avanzado, tool_use | `remote` |
| `planner` | Planificación, diseño de interfaces | planning, structured_output | `remote` |
| `test_author` | Tests de aceptación independientes | code_generation | `remote` |
| `reviewer` | Revisión independiente del diff | code_review, structured_output | `remote` |
| `researcher` | Extracción de claims con esquema | structured_output | `remote` |
| `curator` | Síntesis y redacción de notas de conocimiento post-merge | structured_output, summarization | `remote` o `local` (económico o gratuito) |

Los nombres de rol no implican una escalera. El orden de escalado lo determina la política de selección (§17), no un número. El rol `curator` emplea un modelo de bajo coste (o gratuito según el registry, p. ej. tiers gratuitos de API o modelos locales cuantizados); al operar sobre hechos ya extraídos determinísticamente (§22), no requiere costosas capacidades de razonamiento profundo.

### Model Registry

La clave de una entrada es `(provider, platform, model_id)`: el mismo modelo puede tener fechas de retirada distintas en plataformas distintas.

```yaml
model:
  provider: anthropic
  platform: <api | bedrock | vertex | foundry | ...>
  model_id: "<exact-versioned-model-id>"
  deployment: remote            # remote | local
  lifecycle:
    state: active               # active | legacy | deprecated | retired
    retirement_date: <date | null>
  capabilities: [code_generation, structured_output, tool_use]
  context_limit: <provider-value>
  pricing:
    input_usd_per_million: <provider-value>
    cached_input_read_usd_per_million: <provider-value>
    cache_write_usd_per_million: <provider-value>   # si el proveedor lo cobra aparte
    output_usd_per_million: <provider-value>
    verified_at: <date>
    source: <url>
  availability:
    regions: [eu]
  data_policy:
    classification_max: internal
```

### Verificación del registry

El registry comprueba, por este orden de fiabilidad:

1. **Vía API del proveedor** cuando exista (listado de modelos, capacidades, estado).
2. **Declarativamente** cuando no exista: cada dato de precio y ciclo de vida lleva `verified_at` y `source`. Si `verified_at` supera un TTL configurable, se emite una alarma y, según política, se **bloquea** el uso del modelo.
3. **En runtime**, ante errores del proveedor (modelo retirado, capability no soportada, cuota agotada), se marca la entrada como no disponible y se activa el circuit breaker (§17).

Comprobaciones mínimas: estado de ciclo de vida, disponibilidad regional, capability requerida, soporte de structured output/tool use, cuotas, precio vigente, política de datos.

### Regla de selección

```text
rol requerido → capacidades requeridas
      ↓
política / clasificación de datos (§18)
      ↓
disponibilidad del proveedor / circuit breaker
      ↓
latencia / fiabilidad
      ↓
coste esperado (§17)
      ↓
selección
```

No debe existir lógica del tipo "el rol X = modelo Y para siempre".

---

## 8. Flujo de Control: FSM + Human-in-the-Loop

El ciclo de vida del job se rige por una máquina de estados persistente. El LLM calcula el **contenido** de un estado; el **Job Controller** decide las transiciones. Todas las rutas —incluida la ruta rápida— recorren los mismos estados con distinta intensidad (§5.4).

### 8.1 Flujo principal

```text
IDLE
 ▼
ROUTING ── DOC_LOOKUP ──► DOC_LOOKUP_RUN ──► COMPLETE
   │    ── DEEP_RESEARCH ► RESEARCH_RUN ────► COMPLETE
   │    ── ABSTAIN ──► (abstain_action: PLAN | ASK_USER)
   ▼
DATA_CLASSIFY ──(confidential)──► WAIT_DATA_APPROVAL
   │                                    │ approve / deny→CANCELLED
   ▼◄───────────────────────────────────┘
PLAN_CONTEXT            (mapa estructural ligero, sin contenido)
   ▼
PLAN_SPEC               (Planner completo, o micro-plan en ruta rápida)
   ▼
RISK_FINAL              (Policy Engine; solo puede subir el riesgo)
   ├── LOW ──► (aprobación automática por política)
   └── MEDIUM/HIGH/CRITICAL ──► WAIT_PLAN_APPROVAL
                                   ├── APPROVE ──────────► siguiente
                                   ├── REQUEST_CHANGES ──► PLAN_SPEC (v+1)
                                   └── REJECT ───────────► CANCELLED
   ▼
WORKER_CONTEXT          (contenido mínimo suficiente)
   ▼
WORKTREE_READY          (worktree efímero desde base_commit)
   ▼
TEST_AUTHORING          (solo si el plan exige tests nuevos; §13)
   ▼
EXECUTE                 (Worker + Tool Broker + Code Sandbox; §10)
   ▼
POLICY_VALIDATION       (PatchSet; RISK_DIFF)
   ├── violación ──► POLICY_VIOLATION (STOP)
   ├── riesgo sube ─► WAIT_PLAN_APPROVAL (aprobación invalidada)
   ▼
VERIFY                  (Verification Guard; §13)
   ├── PASS ──────────────► INDEPENDENT_REVIEW
   └── FAIL ──────────────► FAILURE_CLASSIFY
   ▼
INDEPENDENT_REVIEW      (§15)
   ├── PASS ──────────────► (HIGH/CRITICAL) WAIT_DIFF_APPROVAL
   │                         (LOW/MEDIUM)   MERGE_CHECK
   └── FAIL ──────────────► FAILURE_CLASSIFY
   ▼
WAIT_DIFF_APPROVAL ── APPROVE ► MERGE_CHECK
                   ── REQUEST_CHANGES ► EXECUTE (nuevo intento)
                   ── REJECT ► CANCELLED
   ▼
MERGE_CHECK ──(conflicto)──► MERGE_CONFLICT
   ▼
MERGE ──► KNOWLEDGE_UPDATE ──► COMPLETE

FAILURE_CLASSIFY (§14)
   ├── RETRY ────────────► EXECUTE
   ├── CONTEXT_EXPANSION ► WORKER_CONTEXT
   ├── ENV_REPAIR ───────► EXECUTE (o ESCALATED al agotar el tope)
   └── ESCALATED / STOP

Fase post-merge:
   KNOWLEDGE_UPDATE (§22) ──► COMPLETE (no bloqueante; fallo/timeout nunca revierte el merge ni cancela el job)
```

### 8.2 Estados terminales y de pausa

```text
COMPLETE       éxito
CANCELLED      cancelado por el usuario o por rechazo
TIMEOUT        tope de tiempo de reloj del job
STALE_PLAN     el repositorio cambió en el scope aprobado (§8.4)
MERGE_CONFLICT conflicto no resoluble automáticamente
POLICY_VIOLATION violación de política (sin reintento automático)
BUDGET_PAUSED  presupuesto agotado o reserva rechazada
ESCALATED      requiere decisión humana o de rol superior
```

Existe un único estado de reparación de entorno: `ENV_REPAIR` (transitorio, con tope). Un arranque fallido del sandbox es un `ENVIRONMENT_ERROR` (§14), no un estado propio.

### 8.3 PLAN_SPEC

Para tareas `MEDIUM+`, el Planner genera:

1. Archivos a modificar y crear.
2. Interfaces y firmas que se alteran.
3. **Especificación** de casos de prueba y criterios de aceptación (los tests los escribe el Test Author; §13).
4. Riesgo preliminar y razones (el riesgo final lo fija el Policy Engine).
5. Permisos de lectura/escritura/ejecución solicitados.
6. Impacto potencial en otros módulos.
7. Supuestos y puntos de incertidumbre.
8. `base_commit` del repositorio.
9. Clasificación máxima de los datos que se enviarán a modelos remotos (§18).

### 8.4 Aprobación

Una aprobación no autoriza arbitrariamente cualquier cambio posterior. Queda vinculada a:

```yaml
approval:
  kind: plan            # plan | data | diff
  job_id:
  plan_id:
  plan_version:
  base_commit:
  scope_hash:           # incluye archivos, permisos y tests de aceptación congelados
  risk_level:
  data_classification_max:
  policy_version:
  approved_by:
  approved_at:
```

**Regla de obsolescencia (única).** Si `current_commit != approved.base_commit`, el Job Controller calcula los archivos modificados entre ambos commits:

```text
cambios ∩ (scope ∪ dependency_closure ∪ protected_paths) ≠ ∅
→ STALE_PLAN → replan / nueva aprobación

cambios ∩ … = ∅
→ rebase automático sobre current_commit
→ nueva verificación completa
→ evento BASE_REBASED (la aprobación sigue vigente)
```

`APPROVAL_REJECTED` con `REQUEST_CHANGES` genera `PLAN_SPEC(v+1)`; con `REJECT`, `CANCELLED`.

---

## 9. Contexto Estructural: Context Compiler + Tree-sitter + MCP

El objetivo no es simplemente reducir tokens, sino construir el **mínimo contexto suficiente** para resolver la tarea.

### 9.1 Mapa estructural

Tree-sitter extrae, entre otros: firmas, clases, interfaces, tipos exportados, imports, referencias simbólicas cuando estén disponibles, y rutas y metadatos relevantes. La reducción de tokens es un objetivo dependiente del repositorio y se mide (§26); no se fija una cifra.

### 9.2 Dos construcciones de contexto

| Construcción | Cuándo | Contenido |
|---|---|---|
| `PLAN_CONTEXT` | Antes de `PLAN_SPEC` | Mapa estructural ligero: firmas, imports, árbol de rutas, resumen de tests. **Sin cuerpos de archivos** salvo los estrictamente pedidos. |
| `WORKER_CONTEXT` | Tras la aprobación | Dependency closure del scope aprobado: archivos objetivo, imports, tipos/interfaces referenciados, tests relevantes, configuración y metadatos de build/dependencias. |
| `KNOWLEDGE_CONTEXT` | Tras el merge (`KNOWLEDGE_UPDATE`) | Hechos deterministas post-merge extraídos por el Context Compiler sin LLM: firmas, símbolos nuevos/modificados con Tree-sitter, tests añadidos y dependencias modificadas (§22.2). |

Ambas se construyen también en la ruta rápida (con el micro-plan).

### 9.3 Context Expansion

Cuando un worker detecta una dependencia no visible:

```yaml
context_expansion:
  reason: "missing symbol"
  symbols: [PaymentRepository]
  paths_suggested: [src/payments/repository.py]
```

El Context Compiler recupera el mínimo contenido adicional necesario **solo si**:

- las rutas están dentro del `read` del capability token; si no, la petición requiere ampliar el token, lo que puede volver a `WAIT_PLAN_APPROVAL`;
- pasan de nuevo `DATA_CLASSIFY` (§18).

### 9.4 Obsidian / MCP

La memoria persistente vive en namespaces aislados por proyecto: `/vault/Proyectos/{project_id}/`.

Herramientas preferidas de lectura: `read_adr(id)`, `read_project_doc(id)`, `search_project_kb(project_id, query)`. Se evita una API genérica de lectura de filesystem. Todo lo leído del vault se etiqueta `trust: untrusted` (§19).

Para la ingesta y curación de conocimiento, se habilita la herramienta MCP restringida `propose_project_note(...)`. Esta herramienta **únicamente puede escribir en staging** (`/vault/Proyectos/{project_id}/_inbox/`), sin capacidad de sobrescribir notas canónicas ni ADRs, y con límites estrictos de tamaño por nota y número de notas por job (§22.3).

### 9.5 Aislamiento del índice

Todo documento indexado lleva como mínimo:

```text
project_id
namespace_id
document_id
content_hash
classification      # public | internal | confidential | secret (§18)
trust               # trusted | untrusted (§19)
```

El filtrado por proyecto y por clasificación es una condición de seguridad del retrieval, no solo una instrucción de prompt.

### 9.6 Symlinks y path traversal

Toda resolución de ruta debe seguir `resolve → canonicalize → verify namespace → allow`. Se deniegan escapes mediante `..`, symlinks y rutas fuera del namespace autorizado.

### 9.7 Estructura de prompt y caching

Los prompts se construyen con **prefijo estable** (instrucciones del sistema, skill activa, mapa estructural) seguido de la parte variable (tarea, diffs, diagnóstico). Así se maximizan los aciertos de prompt caching del proveedor. El registry (§7) modela por separado lectura y escritura de caché, y la telemetría (§17) los registra.

---

## 10. Modelo de Ejecución: Worker, Tool Broker y Executor

### 10.1 Separación de roles

- El **Worker** es una llamada al modelo (a través del Gateway) que corre en el plano de control. No tiene shell, ni filesystem, ni red propia.
- El **Executor** son los comandos que corren en el Code Sandbox (tests, linters, build).
- El **Tool Broker** media entre ambos: valida cada petición contra el capability token (§23) y la ejecuta.

Dado que el Code Sandbox no tiene red, **el código dentro del contenedor no puede llamar al Gateway**. Toda interacción con un modelo ocurre fuera del sandbox.

### 10.2 Modos del Worker

| Modo | Uso | Descripción |
|---|---|---|
| `single_shot` | Ruta rápida | El Worker recibe `WORKER_CONTEXT` y devuelve ediciones/diff. Sin herramientas. |
| `tool_loop` | Ruta completa | Bucle acotado: el Worker pide herramientas; el Tool Broker las ejecuta y devuelve el resultado. |

### 10.3 Bucle acotado

```text
Worker propone tool_call
      ↓
Tool Broker: valida contra el token (read / write / execute / network)
      ↓
ejecuta (lectura en worktree, comando en Code Sandbox)
      ↓
resultado etiquetado untrusted → Worker
      ↓
repetir hasta propose_patch o max_steps
```

Herramientas permitidas (subconjunto acotado por el token): `read_file`, `search_symbols`, `run_command` (solo comandos del `execute` del token), `propose_patch`, `request_context_expansion`.

**Quién decide cada iteración:** el Worker propone; el Job Controller cuenta pasos, presupuesto y tiempo (`max_steps`, `max_usd`, `max_wallclock`); el Tool Broker aplica el token. Ningún LLM concede permisos.

### 10.4 Aplicación del parche

`propose_patch` entrega ediciones. El controlador construye el `PatchSet` (estampa `job_id`, `base_commit` y hashes; §12), lo aplica en el worktree y pasa a `POLICY_VALIDATION`.

---

## 11. Code Sandbox

### 11.1 Perfil base

Este es el **lugar normativo único** de los controles del sandbox y de los montajes prohibidos; las demás secciones lo referencian.

```text
runtime de contenedores rootless (Docker rootless / Podman)
--network none                    (modo por defecto; ver 11.4)
--cap-drop=ALL
--security-opt=no-new-privileges
sistema de archivos raíz de solo lectura
perfil seccomp
AppArmor/SELinux cuando esté disponible
límites de recursos (11.3)
```

**Nunca se montan por defecto:** `~/.ssh`, `~/.aws`, `~/.config`, `$HOME`, `/run/docker.sock`, el socket de ssh-agent, ni ningún secreto del host.

`--network none` aísla la pila de red del contenedor y aplica al **código en ejecución**, no al Model Gateway.

### 11.2 Perfiles por riesgo

Docker rootless comparte kernel con el host; el código generado a partir de repositorios potencialmente hostiles requiere más aislamiento cuando el riesgo crece:

| Riesgo | Perfil |
|---|---|
| LOW / MEDIUM | Contenedor rootless endurecido (11.1) |
| HIGH | Runtime de aislamiento reforzado (gVisor o Kata) |
| CRITICAL | microVM (Firecracker o equivalente) |

### 11.3 Límites de recursos

```yaml
resources:
  cpus: <limit>
  memory: <limit>
  pids: <limit>
  disk: <limit>
  file_descriptors: <limit>
  timeout_seconds: <limit>
```

El runtime debe comprobar que la plataforma soporta realmente los límites declarados; si no, el job no arranca.

### 11.4 Modos de red del sandbox

| Modo | Descripción | Uso |
|---|---|---|
| `none` | Solo loopback | **Por defecto** |
| `internal-only` | Red interna sin ruta a Internet, con servicios nombrados (p. ej. una base de datos de test) | Tests de integración |
| `allowlist` | Salida a destinos concretos mediante proxy | Excepcional; requiere aprobación explícita y nivel de riesgo ≥ HIGH |

### 11.5 Estructura de filesystem

```text
/source   → read-only
/build    → writable, efímero
/tmp      → tmpfs
/cache    → caché controlada (dependencias precompiladas, verificadas por hash)
```

El sandbox nunca recibe el workspace editable del usuario.

### 11.6 Dependencias

Un sandbox sin red no puede instalar paquetes. Se resuelve así:

- **Imágenes precompiladas**, identificadas por digest, con el lockfile del proyecto y verificación de hashes de paquetes.
- **Mirror/wheelhouse interno** como única fuente permitida en `internal-only` durante la fase de dependencias.
- **Fase `DEPENDENCY_RESOLUTION` separada y auditada:** un cambio de dependencias es un cambio de manifiesto/lockfile, forma parte del PatchSet, se considera al menos `HIGH` (§5.2) y las instalaciones con scripts se ejecutan en un sandbox sin red con paquetes ya descargados.
- El `DEPENDENCY_ERROR` (§14) es la clase de fallo asociada.

### 11.7 Worktree efímero

```text
repositorio base
      ↓
git worktree temporal (rama agentic/<job_id>, desde base_commit)
      ↓
aplicar PatchSet
      ↓
Policy Validation
      ↓
Code Sandbox (verificación)
      ↓
Independent Review
      ↓
Merge Controller
```

Simplifica rollback, diff, reproducibilidad y resolución de conflictos.

---

## 12. PatchSet y Control de Alcance

El Worker **no** devuelve texto libre ni hashes: devuelve **ediciones o un diff**. El controlador construye el `PatchSet` y calcula todos los campos de integridad; un LLM no calcula hashes de forma fiable.

```json
{
  "job_id": "...",                       // estampado por el controlador
  "base_commit": "...",                  // estampado por el controlador
  "files": [
    {
      "path": "src/foo.py",
      "operation": "modify",             // modify | create | delete | rename
      "patch": "...",                    // proporcionado por el Worker
      "mode_before": "100644",           // calculado por el controlador
      "mode_after": "100644",
      "sha256_before": "...",            // calculado por el controlador
      "sha256_after": "..."              // calculado tras aplicar
    }
  ]
}
```

### Validaciones previas (Policy Validation)

- `base_commit` coincide con el del token.
- No hay path traversal ni symlinks que escapen del worktree.
- Los paths están dentro de `write_scope`.
- Las operaciones son permitidas; **no** hay cambios de modo de archivo, symlinks nuevos, submódulos ni binarios salvo autorización explícita.
- Los renames tienen origen y destino dentro de `write_scope`.
- El patch aplica limpiamente.
- El número de archivos y el tamaño del diff están dentro del límite del token.
- No se modifica ningún `protected_path` (§13).
- Ninguna ruta sensible (§5.2) se toca sin que el plan lo haya autorizado.

### Violación de alcance

Si un worker modifica rutas sensibles o protegidas sin autorización explícita —por ejemplo `.github/workflows/*`, `infra/*`, `secrets/*`, scripts de `package.json`, `Makefile`, lockfiles, configuración de hooks o el arnés de tests— el resultado es `POLICY_VIOLATION`. No se consume automáticamente otro intento del mismo worker.

---

## 13. Verification Guard, Arnés y Tests Protegidos

El **Verification Guard** verifica resultados; no impone una metodología concreta como TDD.

### 13.1 Pipeline

```text
PatchSet
   ↓
Policy Validation
   ↓
Restauración del arnés protegido (desde base_commit)
   ↓
Compile / Type Check
   ↓
Lint / Static Analysis
   ↓
Tests de aceptación protegidos
   ↓
Tests del proyecto
   ↓
Tests de integración (si aplica; modo internal-only)
   ↓
Validación contra el manifiesto de tests
```

### 13.2 Política única de rutas protegidas

Una sola lista normativa, referenciada por §5, §12, §13 y las skills:

```yaml
protected_paths:
  tests:
    - tests/protected/**
    - tests/acceptance/**
    - tests/security/**
  harness:
    - conftest.py
    - "**/conftest.py"
    - pytest.ini
    - tox.ini
    - pyproject.toml            # secciones de test/lint/build
    - "**/fixtures/protected/**"
    - .github/workflows/**
    - <configuración de linters y de build>
```

Las skills pueden **añadir** rutas protegidas (p. ej. `tests/protected/migrations/**`), nunca quitarlas. Un plan no puede "autorizar" la modificación de un `protected_path`; si un cambio legítimo lo requiere, es un job `CRITICAL` con aprobación reforzada y con un Test Author independiente.

### 13.3 Protección del arnés

Antes de ejecutar, el Verification Guard **restaura desde `base_commit`** los archivos de `protected_paths`, de modo que un parche no puede alterar tests, `conftest.py`, fixtures ni configuración de verificación.

### 13.4 Autoría independiente de tests

Los tests nuevos de aceptación los escribe el **Test Author** (rol distinto del Worker; §7), a partir del `PLAN_SPEC`. Sus tests se **congelan** y se incluyen en el `scope_hash` aprobado (§8.4). Si los escribe el mismo actor que implementa, no cuentan como verificación independiente.

**Visibilidad:** por defecto, los tests protegidos son **visibles e inmutables** para el Worker (permiten diagnosticar). Para riesgo `HIGH+` puede activarse un conjunto **holdout** que solo ejecuta el Verification Guard y cuyo detalle no se revela al Worker.

### 13.5 Integridad de resultados

La salida del sandbox no es fiable por sí misma: el código bajo prueba puede manipularla. Por eso:

- El Guard ejecuta el runner desde una imagen de confianza; los resultados estructurados los emite el propio runner, no el código del proyecto.
- Los resultados se contrastan con un **manifiesto de IDs de test esperados** (baseline + tests nuevos congelados). Falla la verificación si **baja el número de tests**, o si aumentan `skip`, `xfail`, marcadores o excepciones de colección.
- Para `HIGH+`, el holdout y la revisión independiente (§15) compensan que un código pueda detectar que corre bajo test.

### 13.6 Baseline vs candidate

```text
baseline test result   (antes del parche, en base_commit)
candidate test result  (con el parche)
```

Distingue un **nuevo fallo** de un **fallo preexistente**.

### 13.7 Tests inestables

Un fallo se clasifica antes de decidir el reintento (§14). Un test candidato a `FLAKY_TEST` se reejecuta un número configurable de veces contra baseline y candidate; la cuarentena de tests inestables la gestiona un humano y queda en el manifiesto.

---

## 14. Fallos, Reintentos y Escalado

### 14.1 Enum cerrado de fallos

El **Failure Classifier** es determinista (códigos de salida, informes estructurados, patrones conocidos). Un LLM solo puede desempatar dentro de este enum, y el Job Controller valida la salida.

| Clase | Acción | Tope por job |
|---|---|---|
| `SYNTAX_ERROR` | Retry del worker | 2 |
| `TEST_FAILURE` | Retry con diagnóstico y contexto ampliado si procede | según intentos máx. (§5.3) |
| `CONTEXT_MISSING` | `CONTEXT_EXPANSION` (§9.3) | 2 expansiones |
| `FLAKY_TEST` | Reejecución (§13.7); si persiste, `ESCALATED` | 1 ronda |
| `ENVIRONMENT_ERROR` | `ENV_REPAIR`; arranque fallido del sandbox incluido | 2 |
| `DEPENDENCY_ERROR` | Fase `DEPENDENCY_RESOLUTION` (§11.6) o `ESCALATED` | 1 |
| `POLICY_VIOLATION` | `STOP` (sin reintento automático) | 0 |
| `MERGE_CONFLICT` | Job Controller / usuario | 0 |
| `REVIEW_REJECTED` | Retry con las observaciones del revisor | según intentos máx. |
| `BUDGET_EXHAUSTED` | `BUDGET_PAUSED` | 0 |
| `UNKNOWN` | `ESCALATED` | 0 |

### 14.2 Topes duros por job

Todo job tiene topes **obligatorios**:

```yaml
job_limits:
  max_attempts: <según riesgo, §5.3>
  max_usd: <por proyecto>
  max_wallclock: <por proyecto>
```

Al alcanzar cualquiera, el job pasa a `ESCALATED`, `BUDGET_PAUSED` o `TIMEOUT`. Ningún reintento puede superarlos.

### 14.3 Detección de estancamiento

Se detiene el bucle y se pasa a `ESCALATED` cuando:

- el mismo conjunto de tests falla dos intentos consecutivos con diagnósticos equivalentes, o
- el diff del intento N es idéntico o casi idéntico al del intento N−1, o
- el coste acumulado supera el umbral de progreso sin reducción de fallos.

### 14.4 Regla de coste

Antes de un reintento:

```text
expected_retry_benefit > expected_retry_cost
```

La política puede decidir que el siguiente intento use directamente el rol `worker_strong`. Esta desigualdad **no sustituye** a los topes de 14.2 y 14.3: es una optimización dentro de ellos.

---

## 15. Revisión Independiente y Aprobación del Diff

### 15.1 Independent Review

Se ejecuta tras `VERIFY` y antes del merge. Es distinta del Audit Trail (§25).

- **Determinista:** `git diff --check`, scope, políticas, constraints de ADR (§22), rutas sensibles (§5.2).
- **LLM (según §5.3):** un modelo **distinto** del que generó el cambio y, para `HIGH+`, de **proveedor distinto** cuando exista. Recibe solo el diff, el plan y los criterios de aceptación; no el razonamiento del worker.
- **Salida:** `PASS` o `FAIL` con observaciones estructuradas. `FAIL` pasa por el Failure Classifier como `REVIEW_REJECTED`.

### 15.2 Aprobación humana del diff

Para riesgo `HIGH` y `CRITICAL`, un humano revisa el diff verificado (`WAIT_DIFF_APPROVAL`) antes del merge. En `CRITICAL` la revisión humana es obligatoria, además del revisor LLM. La aprobación de diff es una aprobación versionada (§8.4, `kind: diff`) vinculada al hash del diff.

---

## 16. Merge Controller

El merge es una fase distinta de la generación y de la verificación.

```text
worktree candidato
      ↓
git diff --check
      ↓
auditoría de política (Policy Engine)
      ↓
resultados de verificación y revisión
      ↓
regla de obsolescencia (§8.4)
      ↓
simulación de merge
      ↓
commit atómico en la rama agentic/<job_id>
```

Condiciones mínimas:

- la regla de obsolescencia de §8.4 se cumple (rebase limpio o `current_commit == base_commit`);
- todas las pruebas protegidas pasan y el manifiesto es válido;
- no existen policy violations ni rechazo del revisor;
- no hay conflictos de merge;
- el diff final está dentro del scope aprobado;
- se dispone de las aprobaciones que exige la matriz de riesgo (§5.3).

Los commits van a la **rama de job**. La integración en la rama activa del usuario es una acción explícita, salvo `LOW` con `auto_integrate: true`. Los merges de un repositorio se serializan con un lock.

Tras el commit atómico en la rama de job, el Job Controller transiciona a `KNOWLEDGE_UPDATE` (§8, §22) antes de alcanzar `COMPLETE`. Esta fase post-merge está completamente desacoplada: la persistencia del merge ya es definitiva e inmutable; un fallo, rechazo o timeout en la generación de notas nunca revierte el commit ni altera el resultado exitoso del job.

---

## 17. Model Gateway y Resource Governor

### 17.1 Model Gateway

El Gateway es el **único** componente autorizado a hablar con APIs externas de modelos (zona Z2).

```text
Planner / Worker / Test Author / Reviewer
       ↓
Model Gateway  (Registry + Resource Governor)
       ↓
Provider Adapter
       ↓
Internet
       ↓
Provider API
```

Los workers no gestionan SDKs ni secretos de proveedores. El plano de inferencia necesita conectividad externa cuando se usan modelos remotos; la restricción `network none` es propiedad del Code Sandbox, no del sistema completo.

### 17.2 Rate limiting

`asyncio.Semaphore(max_workers)` controla solo la concurrencia local y no sustituye a un rate limiter. Se requiere:

```text
límite de concurrencia
+ limitador de RPM
+ limitador de TPM
+ cuotas por proveedor / modelo / cuenta
+ gestión de Retry-After
```

### 17.3 Reserva de presupuesto

No basta con comprobar el presupuesto y lanzar llamadas simultáneas:

```text
reservar presupuesto (transacción atómica en el store local; §2)
     ↓
ejecutar
     ↓
reconciliar el uso real
     ↓
liberar la reserva sobrante
```

Una reserva rechazada lleva a `BUDGET_PAUSED`.

### 17.4 Unidades de coste

La unidad presupuestaria principal es USD u otra unidad económica explícita. Se conserva telemetría separada:

```yaml
usage:
  input_tokens:
  cached_input_read_tokens:
  cache_write_tokens:
  output_tokens:
  reasoning_tokens:
  tool_calls:
  provider_cost_usd:
```

### 17.5 Circuit breaker

Un circuit breaker protege frente a fallos del proveedor; no es la comprobación de presupuesto.

```text
CLOSED ──(N fallos / errores 5xx / timeouts en ventana)──► OPEN
OPEN ──(tras cooldown)──► HALF_OPEN
HALF_OPEN ──(éxito)──► CLOSED
HALF_OPEN ──(fallo)──► OPEN
```

Cuando el breaker de un proveedor/modelo está abierto, la política de selección (§7) hace **failover** a otro modelo que cumpla las capacidades, la clasificación de datos y la región.

### 17.6 Política de selección por coste esperado

```text
expected_cost =
    model_cost
  + expected_retry_cost
  + expected_failure_cost
  + expected_human_review_cost
```

Un worker barato que falla repetidamente puede ser más caro que uno de mayor capacidad. Otras responsabilidades del Governor: timeouts, backoff y prioridad de jobs.

### 17.7 Prompt caching

El Gateway aplica y reporta el prompt caching del proveedor sobre el prefijo estable (§9.7). El ahorro se mide con `cached_input_read_tokens` frente a `input_tokens`, y no se asume.

---

## 18. Gobernanza de Datos y Gestión de Secretos

### 18.1 Clasificación de datos

```yaml
data_policy:
  public:
    external_models: allowed
  internal:
    external_models: allowed_with_policy
  confidential:
    external_models: explicit_approval     # WAIT_DATA_APPROVAL
  secret:
    external_models: forbidden
```

**Quién clasifica:** una clasificación **determinista** por rutas, etiquetas y detectores de secretos, definida en la política del proyecto y guardada en el índice (§9.5). Un LLM no clasifica. `DATA_CLASSIFY` se ejecuta antes de enviar cualquier contenido a un modelo remoto y otra vez en cada `Context Expansion`.

`confidential` genera un estado `WAIT_DATA_APPROVAL`; la aprobación es una `approval` de `kind: data` que fija `data_classification_max`. `secret` nunca sale.

### 18.2 Egreso de datos

```text
datos del repositorio
   ↓
clasificación (18.1)
   ↓
redacción
   ↓
política del proveedor (data_policy del registry)
   ↓
Model Gateway
```

### 18.3 Secretos

- `.env` local fuera de git; `.env.example` sin secretos.
- `pydantic-settings` o equivalente para configuración.
- Gitleaks en desarrollo y secret scanning en CI.
- Redacción de logs, prompts, respuestas y trazas.

Un hook local se puede saltar: Gitleaks local **no** es una frontera de seguridad. La frontera es el secret scanning en CI y la protección de push del repositorio.

### 18.4 Secret Broker

Cuando una tarea necesita una credencial real, un broker entrega **credenciales temporales de mínimo alcance** en lugar de montar el secreto completo. El broker sirve **solo** a los componentes con red: **Model Gateway** (claves de proveedores) y **Research Plane** (credenciales de fuentes cuando existan). El Code Sandbox no recibe secretos por defecto (montajes prohibidos: §11.1).

---

## 19. Modelo de Amenazas y Contenido No Confiable

### 19.1 Fuentes y confianza

| Fuente | Confianza | Notas |
|---|---|---|
| Código del repositorio (incluidos README, comentarios, issues locales) | `untrusted` | Puede contener instrucciones inyectadas |
| Dependencias y su documentación | `untrusted` | Riesgo de cadena de suministro |
| Skills de terceros | `untrusted` hasta firmadas/aprobadas | Ver §20 |
| Vault / ADR (Obsidian) | `untrusted` | Editable por humanos y por procesos |
| Contenido web (Research) | `untrusted` | Ver §21 |
| Política, capability tokens, manifiestos del sistema | `trusted` | Generados por componentes deterministas |

### 19.2 Reglas

1. **Herencia:** todo contenido derivado de contenido `untrusted` (incluido `RESEARCH.md`, resúmenes, claims) es `untrusted`.
2. **No es instrucción:** el contenido `untrusted` puede informar, nunca alterar instrucciones del agente, conceder permisos, ampliar tokens ni pedir secretos.
3. **Aislamiento del lector:** un LLM que procesa contenido no confiable, sobre todo web, **no dispone de herramientas** y emite solo salida con esquema validado.
4. **Aprobación con procedencia:** si el Planner solicita permisos o cambios apoyándose en material `untrusted`, la interfaz de aprobación muestra esa procedencia al usuario.
5. **Resultados de herramientas** (salida de comandos, lecturas) llegan al Worker etiquetados `untrusted`.

---

## 20. Sistema de Skills Just-in-Time

Las skills son extensiones modulares. Su manifiesto declara **permisos solicitados**, que son un **techo**, no una concesión.

### Estructura

```text
skills/
├── sql-migrations/
│   ├── metadata.yaml
│   ├── instructions.md
│   └── templates/
```

### Manifest

```yaml
name: sql-migrations
version: 1.0.0
source: <origen>
content_hash: <sha256>
signature: <opcional>
description: "Migraciones SQL reversibles UP/DOWN."

min_risk_level: high          # una skill solo puede SUBIR el riesgo, nunca bajarlo
preferred_worker_capabilities: [sql_generation, schema_reasoning]

match:
  keywords: [migration, ddl, schema]
  paths: ["migrations/**"]
  extensions: [".sql"]

permissions_requested:
  read:
    - "migrations/**"
    - "tests/migrations/**"
  write:
    - "migrations/**"
  execute:
    - "migration-check"

network:
  code_execution: none

verification:
  protected_paths_add:
    - "tests/protected/migrations/**"
  commands:
    - "migration-check"
```

### Reglas de permisos

- El capability token final es la **intersección** de: permisos solicitados por la skill, scope aprobado en el plan y política del proyecto (§23). Una skill no puede ampliar permisos por sí misma.
- La aprobación la determina la matriz de riesgo (§5.3); el manifiesto no lleva un campo de aprobación independiente.
- Las rutas de `protected_paths_add` se añaden a la política única (§13.2); no pueden quitarse.
- El comando de `execute` y el de `verification.commands` deben coincidir con el ejecutable declarado; se validan.
- Las skills están versionadas y con hash; la versión activada se registra en el job (§25).

### Activación

```text
disparador explícito
+ patrones de archivo/ruta
+ tecnología del repositorio
+ coincidencia semántica (último recurso; nunca amplía permisos)
```

Las instrucciones de la skill se cargan solo en el runtime que las necesita, con `trust` propio (§19).

---

## 21. Deep Research con Fuentes Verificadas

El research tiene su propio plano de red (Z3) y su propio modelo de amenazas.

```text
/research <query>
      │
      ▼
1. Source Discovery      → buscador configurable; los resultados se FILTRAN
                           contra el source registry / allowlist de dominios
      ▼
2. Fetcher               → HTTP client o browser aislado, siempre a través
                           del proxy de egreso con allowlist
      ▼
3. Extractor             → Trafilatura / parser (no es un navegador headless)
      ▼
4. Atomic Claims         → LLM lector SIN herramientas; salida con esquema
                           Pydantic: claim + cita + versión (untrusted)
      ▼
5. Evidence Validator    → reglas deterministas (el LLM solo propone)
      ▼
RESEARCH.md              → untrusted (herencia, §19)
```

La llamada LLM de extracción de claims sale por el **Model Gateway** (Z2); el Research Plane (Z3) solo hace fetch.

### 21.1 Evidence policy

No se exige `>= 2 fuentes` para todo hecho. El Evidence Validator evalúa con reglas:

```text
autoridad           (source registry: primaria / oficial / secundaria)
independencia       (dedupe por content_hash, publisher y dominio raíz)
vigencia
versión
proximidad a la fuente primaria
```

Dos páginas que copian el mismo contenido no son dos evidencias independientes: se detectan por hash, cita compartida y publisher.

### 21.2 Snapshot de fuentes

El hash de contenido es **obligatorio**:

```yaml
source:
  url:
  title:
  publisher:
  retrieved_at:
  content_hash:
  document_version:
  section:
```

Para software:

```yaml
software:
  package:
  requested_version:
  resolved_version:
  release_date:
  commit_or_tag:
```

### 21.3 Web como datos no confiables

Todo contenido web recuperado se marca `UNTRUSTED_DATA` y sigue las reglas de §19: no altera instrucciones, no concede permisos y no pide secretos.

### 21.4 Navegación dinámica

```text
página estática → HTTP client
página con mucho JS → browser aislado
```

---

## 22. Memoria, ADR y Constraints Verificables

La memoria persistente del sistema no es un volcado pasivo ni un contexto arbitrario inyectado a los agentes: combina **documentos de arquitectura (ADR) convertibles en restricciones de política** y un **ciclo de curación gobernado con anclas deterministas y aislamiento en staging**.

### 22.1 ADR y compilación a constraints

Los ADR no son solo memoria pasiva: las decisiones relevantes pueden compilarse a constraints ejecutables.

```yaml
adr: ADR-042
adr_version: <hash>
constraints:
  public_api_stability: required
  database_migration_backward_compatible: required
```

El Policy Engine contrasta el PatchSet con esos constraints en `POLICY_VALIDATION` y en la revisión determinista (§15). La versión de cada ADR aplicada se registra en el job (§25). Como el vault es `untrusted` (§19), la **compilación** de un ADR a constraint requiere que el ADR esté marcado como aprobado por un humano; un ADR modificado sin aprobación no genera constraints activos.

### 22.2 Ciclo de actualización de conocimiento post-merge (`KNOWLEDGE_UPDATE`)

Tras el commit en `MERGE`, el Job Controller transiciona al estado `KNOWLEDGE_UPDATE`. Esta fase es **estrictamente no bloqueante**: su ejecución, fallo, timeout o rechazo de notas **nunca revierte un merge exitoso** ni impide alcanzar `COMPLETE`.

```text
MERGE exitoso (commit atómico en rama agentic/<job_id>)
      │
      ▼
KNOWLEDGE_UPDATE (no bloqueante)
      ├── 1. Hechos deterministas (Context Compiler + Tree-sitter, sin LLM)
      │      └── firmas, símbolos nuevos/modificados, tests añadidos, dependencias
      │
      ├── 2. Redacción acotada (Rol Curator: LLM económico o gratuito)
      │      ├── entrada: diff mergeado, PLAN_SPEC, verificación, firmas
      │      ├── prohibido: razonamiento interno / scratchpad del worker
      │      └── salida: prosa (propósito, decisiones, lecciones) con anclas
      │
      ├── 3. Staging (_inbox/) vía MCP restringida (propose_project_note)
      │      └── solo creación, sin sobrescritura, límites de tamaño y cantidad por job
      │
      └── 4. Validación determinista de anclas y secretos
             ├── anclas válidas y sin secretos ──► estado: verified
             └── anclas rotas o secretos ────────► estado: proposed / rechazada
      │
      ▼
COMPLETE
```

#### Entrada limitada (Input Boundary)
El Curator recibe estrictamente:
- Diff mergeado definitivo del job.
- `PLAN_SPEC` aprobado.
- Resultados formales de verificación (`VERIFY`).
- Firmas y símbolos extraídos con Tree-sitter.

> **Regla de aislamiento:** el Curator **nunca recibe el razonamiento del worker** (cadenas de pensamiento, scratchpad o intentos intermedios fallidos). Esto previene que alucinaciones, conjeturas descartadas o sesgos del proceso de generación se consoliden en la memoria persistente del repositorio.

#### Hechos deterministas primero
La extracción de hechos fácticos no depende de la interpretación de un LLM:
- Firmas de funciones y tipos, nuevos símbolos exportados, rutas de tests añadidos y cambios en dependencias son extraídos directamente por el **Context Compiler de forma determinista y sin LLM**.
- El rol **Curator** (LLM económico o gratuito según registry) se concentra únicamente en redactar prosa explicativa: propósito del cambio, decisiones de diseño tomadas y lecciones aprendidas.
- **Anclaje obligatorio:** cada afirmación sustantiva redactada por el Curator debe llevar asociada un ancla explícita y verificable con el formato `archivo:símbolo@commit` (o `archivo:linea@commit`).

### 22.3 Staging y herramienta MCP restringida (`propose_project_note`)

El Curator opera bajo el principio de mínimo privilegio y no tiene acceso de escritura a la base de conocimiento canónica:

1. **Aislamiento en staging:** toda nota generada se escribe exclusivamente en el buzón de entrada del proyecto: `/vault/Proyectos/{project_id}/_inbox/`.
2. **Herramienta MCP restringida (`propose_project_note`):**
   - **Solo creación:** no permite sobrescribir notas canónicas, documentos existentes ni ADRs.
   - **Límites duros por job:** impone cotas por job (p. ej. máximo 3 notas por job y un tope de 8 KB por nota) para evitar spam o envenenamiento por volumen.
3. **Inmutabilidad de canónicas:** ninguna nota generada por modelos entra en la raíz del vault ni en el repositorio canónico sin superar el proceso de validación y promoción.

### 22.4 Promoción a canónica y validación determinista

Antes de que una nota en `_inbox/` pueda considerarse verificada o promocionarse a canónica:

- **Validador determinista:** un componente de software (sin LLM) comprueba automáticamente:
  1. **Existencia de anclas:** verifica que los símbolos o líneas referenciados en `archivo:símbolo@commit` existen en el árbol de Git en el commit especificado.
  2. **Ausencia de secretos:** escanea el texto mediante el Secret Broker y firmas de detección (§18.3) para impedir la persistencia de credenciales, tokens o contenido `secret`.
  3. **Conformidad de clasificación:** asegura que la nota no expone datos clasificados en destinos con menor nivel de protección (§18.1).
- **Puerta de aprobación humana:**
  - Los **ADR** y cualquier nota que pretenda originar o modificar **constraints** para el Policy Engine **requieren siempre aprobación humana explícita**. Ningún modelo tiene autoridad para crear o relajar restricciones arquitectónicas del sistema.

### 22.5 Estados y ciclo de vida de las notas

Las notas de memoria siguen una máquina de estados determinista gobernada por la validez de sus anclas:

```text
proposed ──(validación determinista ok)──► verified ──(content_hash cambia)──► stale ──(nueva nota)──► superseded
    │                                         │
    └──(ancla rota o secreto)──► rejected     └──(revalidación / update)──► verified
```

| Estado | Definición | Tratamiento en Retrieval |
|---|---|---|
| `proposed` | Nota en `_inbox/`, pendiente de verificación determinista o humana | Retrieval secundario / bajo peso; etiquetada como no validada |
| `verified` | Anclas confirmadas en el commit y libre de secretos | Preferencia máxima en el retrieval de contexto |
| `stale` | El `content_hash` del archivo anclado ha cambiado en el repositorio | Fuertemente penalizada o excluida del retrieval activo |
| `superseded` | Reemplazada formalmente por una nota o ADR más reciente | Excluida del retrieval operativo; archivada para auditoría |

**Detección automática de obsolescencia (`stale`):** cuando un commit posterior modifica el archivo correspondiente al ancla de una nota (detectado por cambio de `content_hash`), la nota transiciona de forma inmediata y automática a `stale`. El sistema de retrieval penaliza su puntuación o la descarta completamente, evitando que código refactorizado o eliminado sea guiado por premisas obsoletas.

### 22.6 Metadatos, etiquetas y trazabilidad

Toda nota gestionada almacena un encabezado estructurado de gobernanza:

```yaml
note_id: "note-20260930-7c2a1"
schema_version: "1.0.0"
project_id: "billing-service"
status: proposed                 # proposed | verified | stale | superseded
trust: untrusted                 # siempre untrusted (contenido derivado de LLM, §19)
classification: internal         # heredada del contenido de origen (§18)
anchors:
  - "src/billing/invoice.py:InvoiceProcessor@commit_7c2a1"
  - "tests/billing/test_invoice.py:test_process@commit_7c2a1"
provenance:
  job_id: "job-8f92b"
  base_commit: "commit_7c2a1"
  model: "local/qwen-2.5-coder-7b@ollama"
  prompt_version: "curator-v2.1"
  generated_at: "2026-09-30T13:30:00Z"
```

- **`trust: untrusted`:** al ser generada por un modelo (o residir en el vault), la nota es clasificada como no confiable (§19.1).
- **`classification` heredada:** hereda la clasificación más restrictiva de los insumos analizados; no existe desclasificación automática.
- **Trazabilidad de procedencia:** el `job_id`, commit de referencia, identificador de modelo y versión del prompt quedan inmutables en el Audit Trail (§24, §25).

### 22.7 Política de uso en retrieval

El Context Compiler y los motores de contexto incorporan la memoria bajo dos principios fundamentales:

1. **Solo contexto informativo, nunca instrucción:** las notas recuperadas se presentan al LLM estrictamente como contexto descriptivo de soporte dentro de bloques de datos no confiables. **Nunca se interpretan como instrucciones de control**, bloqueando cualquier vector de inyección indirecta (prompt injection) proveniente de notas históricas.
2. **Prioridad por vigencia:** el mecanismo de retrieval aplica preferencia por notas en estado `verified` y activas. Las notas `stale` se penalizan drásticamente o se filtran para no inyectar ruido o desinformación en el contexto de futuros jobs.

---

## 23. Policy Engine y Capability Tokens

Este componente convierte el diseño de seguridad en política ejecutable. El token de un worker es la **intersección** de la política del proyecto, el scope aprobado y los permisos solicitados por la skill activa (§20).

```json
{
  "job_id": "abc",
  "worker_id": "w-1",
  "risk_level": "MEDIUM",
  "read": ["src/payments/**", "tests/payments/**"],
  "write": ["src/payments/service.py"],
  "execute": ["pytest tests/payments/test_service.py"],
  "network": "none",
  "limits": { "max_files": 3, "max_diff_lines": 150, "max_steps": 12 },
  "trust": "untrusted_inputs_tagged",
  "skills": ["sql-migrations@1.0.0"],
  "expires_at": "..."
}
```

Las cuatro dimensiones se mantienen separadas:

```text
READ CONTEXT
WRITE SCOPE
EXECUTION SCOPE
NETWORK SCOPE
```

Leer algo no implica poder modificarlo. Ningún LLM puede ampliar un token; ampliarlo es una transición del Job Controller que puede requerir nueva aprobación (§9.3).

---

## 24. Event Store, Job Store y TUI

La TUI no es la fuente de verdad: es una vista del estado derivado del log de eventos.

### Job Store

```text
jobs/{job_id}/
├── events.jsonl        # fuente de verdad (append-only, cadena de hashes)
├── manifest.json       # proyección regenerable desde events.jsonl
├── plan.json
├── context.json        # hashes y rutas del contexto enviado
├── patch.json
├── verification.json
├── review.json
├── prompts/            # prompts y respuestas, redactados (retención definida)
├── research/
└── artifacts/
```

Como `prompts/` puede contener datos sensibles, se clasifica igual que los datos del repositorio, se redacta (§18) y tiene retención configurable.

### Integridad del log

Cada evento incluye `prev_hash` y `event_hash` (encadenado). Un log manipulado se detecta al reproducirlo.

### Eventos: uno por transición

Cada transición de la FSM (§8) emite al menos un evento. Conjunto mínimo:

```text
TASK_CREATED         ROUTE_SELECTED        DATA_CLASSIFIED
DATA_APPROVAL_REQUESTED / GRANTED / DENIED
PLAN_CONTEXT_BUILT   PLAN_GENERATED        RISK_ASSESSED (preliminar/final/diff)
APPROVAL_REQUESTED   APPROVAL_GRANTED      APPROVAL_REJECTED
WORKER_CONTEXT_BUILT WORKTREE_READY        TEST_AUTHORED
MODEL_CALL_STARTED   MODEL_CALL_COMPLETED  EGRESS_BLOCKED
BUDGET_RESERVED      BUDGET_RECONCILED     BUDGET_PAUSED
WORKER_STARTED       TOOL_CALL             PATCH_CREATED
POLICY_CHECKED       POLICY_VIOLATION      SANDBOX_STARTED
VERIFICATION_COMPLETED  TEST_FAILED        FAILURE_CLASSIFIED
RETRY_SCHEDULED      CONTEXT_EXPANDED      ENV_REPAIR_STARTED
REVIEW_COMPLETED     BASE_REBASED          STALE_PLAN
TIMEOUT              ESCALATED             MERGE_CONFLICT
MERGE_COMPLETED      KNOWLEDGE_UPDATE_STARTED NOTE_PROPOSED
NOTE_VALIDATED       KNOWLEDGE_UPDATE_COMPLETED
JOB_FAILED           JOB_CANCELLED
```

Cada evento contiene:

```yaml
event_id:
job_id:
timestamp:
schema_version:
actor:
state:
payload:
prev_hash:
event_hash:
```

### TUI

Textual/Rich consume eventos y muestra únicamente combinaciones válidas de la FSM (p. ej. en `VERIFY` el planner está inactivo):

```text
┌─ [Agentic OS] FSM: VERIFY ───────────────────────────────────────┐
│ Job: abc123   Risk: HIGH   Budget: 42%                           │
├──────────────────────────────────────────────────────────────────┤
│ MODEL GATEWAY                                                    │
│ planner: IDLE       worker: 0/3 (verificando)                    │
│ provider quota: OK  reserved: $0.00   spent: $0.31               │
├──────────────────────────────────────────────────────────────────┤
│ VERIFICATION                                                     │
│ compile: PASS   lint: PASS   protected tests: PASS               │
│ project tests: 48/48 PASS   manifest: OK                         │
├──────────────────────────────────────────────────────────────────┤
│ PLAN                                                             │
│ base_commit: 7c31...   scope: 3 files   plan v2 (aprobado)       │
└──────────────────────────────────────────────────────────────────┘
```

---

## 25. Observabilidad, Reproducibilidad y Auditoría

Cada job registra (el Audit Trail permite reconstruir por qué se produjo un patch concreto):

```yaml
job:
  job_id:
  repository:
  base_commit:
  final_commit:

routing:
  intent:
  preliminary_risk:
  confidence:
  router_model_version:

risk:
  final:
  diff:

approvals:            # registros de §8.4
  plan:
  data:
  diff:

context:
  plan_context_hash:
  worker_context_hash:
  adr_versions:

models:
  router_model:
  planner_model:
  worker_models:
  test_author_model:
  reviewer_model:
  parameters:         # temperatura, límites, seed cuando exista

runtime:
  skill_versions:
  prompt_template_versions:
  tool_versions:
  sandbox_image_digest:
  dependency_lock_hash:
  policy_version:

usage:
  input_tokens:
  cached_input_read_tokens:
  cache_write_tokens:
  output_tokens:
  reasoning_tokens:
  provider_cost_usd:

verification:
  tests_run:
  manifest_ok:
  failures:
  retries:
  final_status:

research:
  sources:
  source_hashes:
```

---

## 26. Plan de Medición (Rendimiento, Latencia y Costes)

Esta sección define **cómo se medirá** el sistema. No contiene estimaciones: ninguna mejora se presenta como garantizada hasta disponer de datos.

### 26.1 Diseño experimental

- **Baseline explícito:** un agente de referencia definido y versionado (p. ej. el flujo habitual de un asistente de código con el mismo modelo). Para aislar el efecto de la arquitectura del de la calidad del modelo, ambos usan **el mismo modelo** salvo en experimentos de routing entre modelos.
- **Muestreo estratificado por riesgo:** las tareas de riesgo `HIGH/CRITICAL` se sobremuestrean; si no, las tasas de *false-direct* y de violaciones quedan sin potencia estadística.
- **Repeticiones** para variabilidad: `pass@k` y p50/p90/p95 por clase de tarea.
- **Márgenes de no inferioridad** definidos de antemano para calidad (compilación, tests, regresión); las mejoras de coste y latencia solo cuentan si se cumple la no inferioridad.

### 26.2 Métricas

| Métrica | Baseline | Criterio de éxito (a fijar antes del experimento) | Cómo medir |
|---|---|---|---|
| Tokens de entrada | medir | reducción ≥ X % con no inferioridad de calidad | tokens/job |
| Tokens de salida | medir | reducción ≥ X % | tokens/job |
| Coste por tarea exitosa | medir | reducción ≥ X % | USD/tarea exitosa |
| Latencia p50 / p95 | medir | ≤ Y ms por clase | ms/job |
| Patch apply success | medir | no inferior al baseline (margen δ) | % |
| Compile success | medir | no inferior (δ) | % |
| Protected test pass | medir | no inferior (δ) | % |
| Retry / escalation rate | medir | sin aumento de fallos | % |
| Human review time | medir | reducción ≥ Z % | min/job |
| Regression rate | medir | no superior al baseline (δ) | % |
| Rejected or stale note rate | medir | tasa controlada (≤ W %) en staging y vault | % notas |
| Memory net utility | medir | ratio positivo: mejora de éxito (pass@k) o reducción de reintentos > coste de tokens inyectados | ratio (Δ éxito / kTokens) |

`X`, `Y`, `Z`, `W` y `δ` son parámetros de decisión del proyecto: se fijan **antes** de ejecutar el benchmark.

### 26.3 Tamaño del benchmark y potencia

Con 100–300 tareas reales, observar **0** false-direct solo permite afirmar un límite superior del orden de **1 %** con confianza del 95 % (regla de tres: ≈ 3/n). Para p95 por clase hacen falta muchas más muestras por clase. Por tanto:

```text
tareas reales: ≥ 300 en total, estratificadas por riesgo
repositorios: 5–10, múltiples lenguajes y tamaños
sobremuestreo de HIGH/CRITICAL para false-direct y violaciones
baseline vs Agentic OS, mismas tareas y mismo modelo
repeticiones suficientes para p50/p90/p95 por clase
```

### 26.4 Métricas críticas

```text
false-direct rate (y tasa de reescalado)
policy violation rate
protected-test modification rate (intentos detectados)
regression rate
cost per successful task
human minutes per successful task
rejected or stale note rate
memory net utility (tasa de éxito vs overhead de tokens)
```

**Medición del impacto de la memoria:** la memoria persistente debe someterse a prueba experimental continua. Se medirá si la presencia de notas en el contexto mejora efectivamente la tasa de éxito y reduce reintentos, o si por el contrario únicamente consume tokens y añade ruido. Una memoria defectuosa o desactualizada empeora el rendimiento global del sistema; si la utilidad neta es nula o negativa, el retrieval de notas se deshabilita por política.

No se usan afirmaciones como "regresión nula" o ">90 % de ahorro" salvo que el benchmark las demuestre dentro del conjunto y la metodología documentados.

---

## 27. Criterios de Aceptación del Sistema

El proyecto no se considera listo hasta demostrar, al menos, lo siguiente. Cada bloque indica su prioridad de implementación (§28).

### Routing (P0 v0 reglas · P2 clasificador)

```text
- router local-first con abstención configurable
- false-direct medido y tasa de reescalado medida
- toda intención con rama definida en la FSM
```

### Security (P0)

```text
- code sandbox sin red por defecto y sin montajes prohibidos
- model gateway como único egreso hacia proveedores
- secretos nunca expuestos por defecto
- protected_paths y arnés restaurados desde base_commit
- manifiesto de tests validado en cada verificación
- contenido no confiable etiquetado y heredado
```

### Governance (P0)

```text
- plan versionado
- aprobación vinculada a base_commit y scope_hash
- riesgo monótono (preliminar → final → diff)
- policy engine aplicado al patch
- aprobación del diff en HIGH/CRITICAL
- integración en rama de job, nunca en la activa por defecto
```

### Execution (P0/P1)

```text
- sandbox reproducible (imagen por digest, lockfile con hashes)
- límites de recursos comprobados
- clasificación de fallos con enum cerrado y topes por job
- context expansion con re-clasificación de datos
```

### Economics (P1)

```text
- presupuesto reservado atómicamente
- cuotas por proveedor/modelo/cuenta
- coste por job registrado
- fallback de modelo basado en coste esperado y circuit breaker
```

### Research (P1)

```text
- fuentes versionadas y con hash
- contenido web tratado como no confiable
- evidencia con autoridad e independencia
```

### Medición (P0)

```text
- harness de benchmark y baseline medido antes de optimizar
```

---

## 28. Priorización de Implementación

### P0 — antes de cualquier MVP serio

1. Harness de benchmark y medición del baseline (§26).
2. Job Controller + FSM + aprobación versionada (§8).
3. Policy Engine + capability tokens + matriz de riesgo (§5, §23).
4. Router v0 basado en reglas y slash commands (§6).
5. Model Registry / Model Gateway (§7, §17).
6. Ephemeral Worktree + PatchSet estructurado (§11, §12).
7. Protected Verification Suite (arnés, manifiesto, Test Author) (§13).
8. Separación de red por zonas (§4).
9. Job/Event Store con cadena de hashes (§24).
10. Secret & Data Policy (§18).
11. Merge Controller (rama de job, lock) (§16).

### P1 — inmediatamente después

1. Context Compiler + dependency closure (§9).
2. Failure Classifier, topes y detección de estancamiento (§14).
3. Context Expansion con re-clasificación de datos.
4. Rate limiting por provider/model/account y circuit breaker (§17).
5. Budget reservation/reconciliation y **modelo de fallback por coste esperado** (requerido por §27).
6. Health checks y ciclo de vida de modelos.
7. Runtime de skills (§20), pipeline de research y Evidence Store (§21), compilación de ADR y ciclo de curación post-merge en staging (`_inbox/`) (§22).
8. Independent Review LLM (§15).

### P2 — optimización

1. Mejora del clasificador local (embeddings/ONNX).
2. Caching avanzado (§9.7, §17.7).
3. TUI avanzada.
4. Ajuste fino de la política de coste esperado.
5. Benchmarks longitudinales.

---

## 29. Decisiones Arquitectónicas Clave

**D1 — La red se separa por función, no se elimina globalmente.** Los modelos remotos necesitan conectividad con sus proveedores; el Code Sandbox no.

**D2 — La autoridad del worker se define por capabilities.** El worker no recibe confianza global; recibe permisos temporales, explícitos e intersectados con la política.

**D3 — La aprobación humana es una autorización versionada.** No es un simple "Enter": autoriza un plan, un scope y un estado concreto del repositorio, y se invalida si el riesgo sube.

**D4 — Los tests protegidos y el arnés son parte de la frontera de seguridad.** La verificación debe ser independiente del actor que genera el código: autoría separada, restauración desde `base_commit` y manifiesto de tests.

**D5 — Los modelos son recursos intercambiables descritos por rol.** IDs por `(proveedor, plataforma, model_id)` con ciclo de vida, capacidades y precio verificados.

**D6 — El contexto se expande bajo demanda y bajo política.** Minimizar contexto no es amputarlo: cada expansión respeta el token y la clasificación de datos.

**D7 — El research no comparte el modelo de amenaza del code execution.** Internet es necesaria para investigar, pero el contenido obtenido es no confiable y esa etiqueta se hereda.

**D8 — El riesgo lo fija el cambio real, no el prompt.** El router elige un camino; el Policy Engine fija el riesgo sobre scope y diff, y este solo puede subir.

**D9 — El LLM propone; los componentes deterministas deciden.** Transiciones, permisos, presupuesto y clasificación de fallos no dependen de la salida de un modelo.

**D10 — La memoria es desacoplada, determinista y anclada a evidencia.** La actualización de conocimiento post-merge (Curator) nunca bloquea el job ni compromete un merge; los hechos se extraen sin LLM con Tree-sitter, la prosa exige anclas archivo:símbolo@commit, la escritura se aísla en staging (_inbox/) y las notas transicionan automáticamente a stale si cambia el hash del código.

---

## 30. Referencias Externas

- Docker — `none` network driver: https://docs.docker.com/engine/network/drivers/none/
- Docker — network drivers: https://docs.docker.com/engine/network/drivers/
- GitHub Changelog — GitHub Models retirado el 30 de julio de 2026: https://github.blog/changelog/2026-07-01-github-models-is-being-fully-retired-on-july-30-2026/
- Anthropic — Model deprecations: https://platform.claude.com/docs/en/about-claude/model-deprecations
- OpenAI — Prompt caching (referencia para §9.7 y §17.7): https://developers.openai.com/api/docs/guides/prompt-caching

---

## 31. Cierre

La arquitectura mantiene la tesis central del proyecto:

```text
routing local
→ riesgo (preliminar → final → diff)
→ planificación acotada
→ contexto mínimo suficiente
→ workers con capabilities limitadas
→ ejecución efímera y aislada
→ verificación determinista con arnés protegido
→ revisión independiente y aprobación humana según riesgo
→ merge auditado en rama de job
```

Seguridad, coste y contexto son **políticas ejecutables y observables**, no propiedades implícitas de los componentes. La red no se bloquea en todo el sistema: se habilita donde es necesaria —Model Gateway y Research— y se bloquea por defecto en el entorno donde se ejecuta código generado.

---

## Apéndice A — Historial de Cambios y Estado de Actualidad

### A.1 Estado de actualidad a 2026-09-30

Estos datos caducan; **no** forman parte del texto normativo y el registry (§7) debe obtenerlos por API o con `verified_at`.

- **GitHub Models** se retiró el 30 de julio de 2026 para todos los clientes (playground, catálogo, API de inferencia y BYOK).
- **Anthropic API:** Claude Sonnet 3.7 se retiró el 19 de febrero de 2026 y Claude Sonnet 4 el 15 de junio de 2026.
- **Ciclo de vida por plataforma:** un mismo modelo puede tener fechas distintas según plataforma. Un calendario de terceros indica, por ejemplo, para Claude Sonnet 4 en Amazon Bedrock un fin de vida el 14 de octubre de 2026 (dato de fuente secundaria; verificar en la plataforma).

### A.2 Cambios de la v2.0 a la v2.1

| Área | Cambio |
|---|---|
| Riesgo y FSM | Riesgo en tres fases con regla monótona (§5); FSM única con rama para cada intención y ruta rápida gobernada (§8); `PLAN_CONTEXT`/`WORKER_CONTEXT` |
| Nomenclatura | Glosario (§3): Planner vs Job Controller, un solo Policy Engine, `Local Router`, sin "Tier" ni "Orchestrator" |
| Ejecución | Worker / Tool Broker / Executor (§10); PatchSet con hashes estampados por el controlador (§12) |
| Verificación | Arnés protegido y restaurado, manifiesto de tests, Test Author independiente, política única de `protected_paths` (§13) |
| Fallos | Enum cerrado, topes duros y detección de estancamiento (§14) |
| Revisión | `INDEPENDENT_REVIEW` y aprobación humana del diff en HIGH/CRITICAL (§15); commits a rama de job (§16) |
| Sandbox | Perfiles por riesgo, modos de red, fase de dependencias (§11) |
| Seguridad | Modelo de amenazas y herencia de `untrusted` (§19); skills con permisos como techo (§20); datos: clasificación determinista y `WAIT_DATA_APPROVAL` (§18) |
| Economía | Registry por rol y por plataforma, `verified_at`, coste de escritura de caché, circuit breaker real (§7, §17) |
| Medición | Plan de medición con potencia estadística y baseline definido (§26); harness en P0 (§28) |
| Higiene | Eliminados los restos de la versión anterior y la duplicación (`--network none`, montajes prohibidos, §21 antigua "Seguridad de Open Source"); topología declarada (§2); diagramas alineados |
| Memoria y Curación | Rol `curator` (económico/gratuito) y estado post-merge `KNOWLEDGE_UPDATE` no bloqueante (§8, §22); extracción determinista de hechos sin LLM (§9.2, §22.2); anclas `archivo:símbolo@commit`; staging en `_inbox/` con MCP restringida (`propose_project_note`); ciclo `proposed` → `verified` → `stale` → `superseded`; métricas de utilidad neta de memoria en §26 |

## Apéndice B — Puntos Abiertos

- Los umbrales de la matriz de riesgo (§5.3), los topes de §14 y los parámetros del router (§6) son valores por defecto que deben calibrarse.
- La política de retención de `prompts/` (§24) y el TTL de `verified_at` (§7) requieren decisión del proyecto.
- La URL `docs.github.com/en/github-models` de la v2.0 no se pudo verificar; se sustituyó por el changelog verificado. La referencia de OpenAI sobre prompt caching tampoco se pudo verificar y se conserva como referencia genérica.
- Está por decidir si `HIGH+` usa holdout de tests por defecto (§13.4).
