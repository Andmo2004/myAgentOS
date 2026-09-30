# myagentos (Agentic OS v2.1)

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Type Checked with Mypy Strict](https://img.shields.io/badge/mypy-strict%20checked-green.svg)](http://mypy-lang.org/)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Tests: Pytest](https://img.shields.io/badge/tests-133%20passed-brightgreen.svg)](https://docs.pytest.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-purple.svg)](LICENSE)

**myagentos** es una implementación canónica y de grado de producción de un **Sistema Operativo Agéntico para Ingeniería de Software**, gobernado por contratos formales, seguridad de mínimo privilegio, evidencia verificable y preservación monótona de riesgo conforme a la especificación técnica [`docs/agentic-os-v2.1.md`](docs/agentic-os-v2.1.md).

A diferencia de los asistentes de código tradicionales que confían ciegamente en salidas no acotadas de Modelos de Lenguaje (LLMs), **myagentos** opera bajo una premisa fundamental:
> **El LLM propone; los componentes deterministas del sistema deciden y ejecutan.**

---

## Tesis Arquitectónica

```text
Enrutamiento Local Determinista
 └── Clasificación de Riesgo en Tres Fases (Preliminar ➔ Final ➔ Diff)
      └── Planificación Acotada & Micro-Planes Gobernados
           └── Compilación de Contexto Mínimo Suficiente (Token-Bounded)
                └── Workers Restringidos por Capability Tokens Desacoplados
                     └── Sandboxing Aislado sin Red por Defecto & Worktrees Efímeros
                          └── Verificación Determinista con Arnés Protegido
                               └── Revisión Independiente (Ceguera Estricta) & Aprobación Humana
                                    └── Merge Serializado en Rama de Job con Mutex Lock
                                         └── Memoria Continua Post-Merge Desacoplada (Curator)
```

---

## Flujo End-to-End del Sistema

```mermaid
flowchart TD
    Prompt([Task Prompt]) --> Router[1. Local Router]
    Router -->|Ruta Rápida| MicroPlan[Micro-Plan Determinista]
    Router -->|Ruta Planificada| ContextComp[2. Context Compiler]
    ContextComp --> Planner[3. Planner Agent]
    Planner --> RiskPolicy[4. Policy Engine - Risk Assessment]
    MicroPlan --> RiskPolicy
    
    RiskPolicy -->|Riesgo >= MEDIUM| WaitApproval{5. Aprobación de Plan}
    RiskPolicy -->|Riesgo LOW| FastApprove[Auto-Aprobación]
    WaitApproval -->|Aprobado| WorkerCtx[6. Worker Context & JIT Skills]
    FastApprove --> WorkerCtx
    
    WorkerCtx --> Sandbox[7. Worker Loop & Sandbox Z4]
    Sandbox --> PatchApplier[8. PatchSet Estructurado]
    PatchApplier --> PolicyCheck{9. Policy Engine Scope Check}
    
    PolicyCheck -->|Violación| FailureDiag[Failure Classifier & Healing]
    PolicyCheck -->|Válido| VerifyGuard[10. Verification Guard]
    
    VerifyGuard -->|Tests Fallan| FailureDiag
    FailureDiag -->|Reintento| Sandbox
    
    VerifyGuard -->|Tests Pasan| Reviewer[11. Independent Reviewer]
    Reviewer --> MergeCheck[12. Detección de Obsolescencia de Plan]
    
    MergeCheck -->|HEAD Cambió Orthogonal| AutoRebase[Rebase Automático & Re-Verify]
    MergeCheck -->|HEAD Colisiona con Scope| StalePlan[Bloqueo STALE_PLAN]
    AutoRebase --> Merge[13. Merge Controller - agentic/job_id]
    MergeCheck -->|Limpio| Merge
    
    Merge --> Curator[14. Curator Role - Knowledge Update]
    Curator --> Complete([Trabajo Completado & Audit Trail Íntegro])
```

---

## Subsistemas Principales y Garantías de Seguridad

### 1. Enrutamiento Local y Detección de Riesgo (§6)
- **Local-First sin coste LLM:** Enrutamiento determinista por prefijos (`/direct`, `/plan`, `/research`, `/doc`) y expresiones regulares.
- **Detección de Falsos Directos (*False-Direct Prevention*):** Tareas con disparadores `/direct` dirigidas a rutas críticas (`auth/`, migraciones DB, secretos) son escaladas forzosamente a `PLANNED_CODE` para impedir accesos desgobernados.

### 2. Máquina de Estados Finita (FSM) y Cadena Criptográfica (§8, §24)
- **FSM Determinista:** Estados formales (`ROUTING`, `PLANNING`, `WAIT_PLAN_APPROVAL`, `WORKER_LOOP`, `VERIFYING`, `FAILURE_CLASSIFY`, `INDEPENDENT_REVIEW`, `MERGING`, `KNOWLEDGE_UPDATE`).
- **Audit Trail Criptográfico SHA-256:** Cada evento se registra de forma inmutable en `.myagentos/jobs/{job_id}/events.jsonl`, vinculado al hash del evento anterior:
  $$\text{event\_hash} = \text{SHA256}(\text{event\_id} + \text{job\_id} + \text{state} + \text{prev\_hash} + \text{payload})$$
  Cualquier modificación o truncamiento es detectado de forma inmediata e irreversible.

### 3. Capability Tokens y Mínimo Privilegio (§5, §23, AUD-027)
- **Desacoplamiento en 4 Dimensiones:**
  - `read_scope`: Patrones glob de rutas legibles en el repositorio.
  - `write_scope`: Rutas autorizadas para creación/modificación (estrictamente limitadas al plan).
  - `execute_scope`: Comandos explícitos permitidos en el sandbox.
  - `network_scope`: Acceso a red deshabilitado por defecto (`NONE`).
- **Invariante Monótona de Riesgo:**
  $$\text{Riesgo}_{\text{efectivo}} = \max(\text{Riesgo}_{\text{actual}}, \text{Riesgo}_{\text{nuevo}})$$
  Ningún componente puede rebajar unilateralmente el nivel de riesgo asignado a un trabajo.

### 4. Compilador de Contexto y Cierre de Dependencias (§9)
- **Extracción AST sin Ruido:** Extracción estática de firmas públicas, interfaces y exports mediante Tree-sitter.
- **Cierre Transitivo de Dependencias:** Rastreo de imports locales que alimenta la detección de impacto cruzado y obsolescencia.
- **Redactor Determinista de Secretos:** Bloqueo y ofuscación automática de claves privadas, tokens y credenciales de producción antes de ser incorporadas a cualquier prompt.

### 5. Sandboxing Aislado y Worktrees Efímeros (§11, §16)
- **Drivers Pluggables:** `DockerSandboxDriver` (rootless, `--network none`, `--cap-drop=ALL`), `SubprocessDriver` y `MockSandboxDriver`.
- **Aislamiento en Worktrees:** Las modificaciones se ensayan en worktrees Git temporales en `.myagentos/worktrees/{job_id}`.
- **Merge Seguro:** Commits atómicos serializados bajo mutex lock en `.myagentos/merge.lock` hacia ramas dedicadas `agentic/{job_id}`.

### 6. Arnés de Verificación Protegido y Test Author (§13)
- **Restauración de Rutas Protegidas:** Antes de ejecutar cualquier test, [`VerificationGuard`](src/myagentos/verification/guard.py) restaura incondicionalmente desde `base_commit` todas las rutas protegidas (`tests/protected/**`, `conftest.py`, workflows de CI/CD), impidiendo que un worker debilite las aserciones de seguridad.
- **Manifiesto de Tests Obligatorio:** Verificación del recuento y nombres de los tests ejecutados contra la especificación aprobada.

### 7. Clasificador de Fallos y Auto-Sanación (§14, AUD-012)
- **Taxonomía Cerrada de Fallos:** Categorización determinista (`TEST_FAILURE`, `SYNTAX_ERROR`, `DEPENDENCY_ERROR`, `PROTECTED_TEST_MODIFIED`, `STAGNATION_DETECTED`, `RETRY_EXHAUSTED`).
- **Detección de Estancamiento:** Comparación de hashes de diffs entre iteraciones sucesivas para abortar bucles infinitos improductivos.

### 8. Revisor Independiente y Aprobación de Diff (§15, AUD-013, AUD-014)
- **Ceguera Estricta:** El revisor evalúa el `PatchSet` contra el `PlanSpec` sin acceso a los pensamientos internos, scratchpads ni trazas previas del worker.
- **Defensa Adversarial:** Inspección de alteraciones no declaradas, inyecciones de credenciales y desbordamiento de alcance.
- **Aprobación Humana de Diff:** Mandatoria para trabajos con riesgo `HIGH` o `CRITICAL`.

### 9. Rol Curator y Memoria Continua Post-Merge (§22, AUD-018)
- **Actualización Post-Merge No Bloqueante:** [`CuratorAgent`](src/myagentos/curator/agent.py) opera en la fase `KNOWLEDGE_UPDATE` tras consolidarse el merge.
- **Extracción Factual sin LLM:** Símbolos y relaciones extraídos con Tree-sitter.
- **Anclaje Obligatorio:** Notas estructuradas con anclas canónicas `archivo:símbolo@commit` o `archivo:linea@commit`.
- **Staging Aislado `_inbox/`:** Las notas se proponen en `.myagentos/vault/projects/{project_id}/_inbox/` con política create-only (tope de 3 notas por job y 8 KB por nota), escaneo determinista de secretos y transición automática a `stale` si commits posteriores modifican los archivos anclados.

### 10. Detección de Obsolescencia de Plan y Rebase (§8.4, AUD-025, AUD-026)
- **Regla Única Normativa de Obsolescencia:**
  $$\text{cambios} \cap (\text{scope} \cup \text{dependency\_closure} \cup \text{protected\_paths}) \neq \emptyset \implies \text{STALE\_PLAN}$$
- Si los commits concurrentes en el repositorio raíz son ortogonales, myagentos realiza un rebase automático en el worktree, re-ejecuta la verificación completa y emite el evento `BASE_REBASED`. Si colisionan, el plan es invalidado y se requiere replanificación.

### 11. Sistema de Skills Just-in-Time y Techos de Permiso (§20, AUD-027)
- **Principio Normativo de Techo:**
  $$\text{skill\_permissions} = \text{requested\_permissions} \cap \text{approved\_scope} \cap \text{project\_policy}$$
  Las skills declaradas o emparejadas Just-in-Time actúan estrictamente como un límite superior; nunca pueden expandir los permisos fuera del plan aprobado.
- **Rutas Protegidas Aditivas:** Las skills pueden incorporar rutas protegidas adicionales (`protected_paths_add`), pero jamás eliminar las existentes.
- **Elevación Monotónica de Riesgo:** `effective_risk` toma el valor máximo entre el riesgo base y el riesgo mínimo de las skills activas.

### 12. Arnés de Benchmark Empírico y Comparador Baseline (§26, §28)
- **Evaluación Científica:** Comparación bajo el mismo modelo LLM entre un `BaselineAgent` (asistente directo no gobernado) y `PipelineOrchestrator` de myAgentOS.
- **Dataset Estratificado:** Casos de prueba en 5 categorías: `LOW_MECHANICAL`, `FEATURE_MEDIUM`, `HIGH_AUTH_CRITICAL`, `ADVERSARIAL_SECURITY` y `PCA_CONTINUITY`.
- **Telemetría Completa:** Medición de latencia (p50/p95), tokens, coste estimado USD, tasas de defensa de políticas y preservación de integridad de la cadena criptográfica.

---

## Requisitos y Configuración de Entorno

- **Python:** `>= 3.12`
- **Gestor de Paquetes:** [`uv`](https://docs.astral.sh/uv/) (recomendado) o `pip`.
- **Git:** `>= 2.30`

### Instalación Rápida con `uv`

```bash
# Clonar el repositorio
git clone https://github.com/Andmo2004/myAgentOS.git
cd myAgentOS

# Crear entorno virtual y sincronizar dependencias
uv venv
source .venv/bin/activate
uv sync
```

---

## Guía de Uso del CLI (`myagentos`)

### 1. Ejecución Autónoma de Tareas (`run`)

Ejecuta el ciclo de vida completo (enrutamiento, planificación, sandboxing, verificación determinista, revisión y curación):

```bash
# Ejecución con auto-aprobación para entornos no interactivos
uv run myagentos run "Corrige la validación de tokens en src/auth.py" --auto-approve

# Especificar un modelo concreto registrado en el Gateway
uv run myagentos run "Añade tipado estricto a src/math_ops.py" --model mock
```

### 2. Inspección del Enrutador Local (`route`)

Inspecciona la clasificación de intención, regla aplicada y riesgo preliminar sin invocar inferencias externas:

```bash
uv run myagentos route "/direct fix typo in README.md"
uv run myagentos route "Refactor database migrations and foreign keys"
```

### 3. Estado del Trabajo y Auditoría Criptográfica (`status` y `verify`)

```bash
# Ver estado actual en la FSM, plan activo y recuento de eventos
uv run myagentos status job-d327c605

# Verificar matemáticamente la integridad de la cadena de hashes SHA-256
uv run myagentos verify job-d327c605
```

### 4. Arnés de Benchmark Empírico (`benchmark` o `bench`)

Ejecuta la suite de evaluación comparativa contra el agente baseline de referencia:

```bash
# Ejecutar suite rápida (smoke) con visualización de tablas comparativas
uv run myagentos benchmark --suite smoke

# Ejecutar suite de pruebas de seguridad y adversariales
uv run myagentos benchmark --suite security

# Exportar reporte estadístico completo a JSON
uv run myagentos benchmark --suite full --output reports/benchmark_full.json
```

### 5. Auditoría de Continuidad de Proyectos (`continue`)

Herramienta de diagnóstico de línea base (Project Continuation Audit - PCA):

```bash
# Diagnóstico estático y dinámico de salud del repositorio
uv run myagentos continue run --dynamic

# Generar informe formal de hallazgos
uv run myagentos continue report
```

---

## Estructura Modular del Proyecto

```text
myAgentOS/
├── src/myagentos/
│   ├── benchmark/           # Arnés empírico, baseline agent y dataset estratificado (§26, §28)
│   ├── continuity/          # Project Continuation Audit (PCA) y sintetizador de estado
│   ├── context/             # Compilador de contexto, closure de dependencias y sanitizador (§9)
│   ├── core/                # Modelos Pydantic v2 inmutables, errores y EventStore criptográfico
│   │   ├── models/          # RiskLevel, Event, CapabilityToken, PlanSpec, PatchSet, FailureRecord
│   │   └── store/           # EventStore append-only (SHA-256 hash chain) y StateProjector
│   ├── curator/             # Rol Curator, extracción Tree-sitter y vault de staging (§22, AUD-018)
│   ├── failure/             # Clasificador de fallos determinista y estrategias de curación (§14)
│   ├── fsm/                 # Controlador de ciclo de vida formal JobController y transiciones (§8)
│   ├── gateway/             # Model Gateway (Zona Z2), adaptadores OpenAI, Gemini y Mock (§7, §17)
│   ├── pipeline/            # Orquestador integral PipelineOrchestrator y PipelineResult (§8)
│   ├── planner/             # PlannerAgent, esquemas estructurados de plan y micro-planes (§7)
│   ├── policy/              # PolicyEngine, enforcer de reglas de alcance y detector de señales (§5)
│   ├── reviewer/            # IndependentReviewer con ceguera estricta y aprobación de diff (§15)
│   ├── router/              # LocalRouter v0 con comandos slash y heurísticas de riesgo (§6)
│   ├── sandbox/             # Code Execution Sandbox (Zona Z4): Docker, Subprocess y Mock (§11)
│   ├── skills/              # Runtime de Skills Just-in-Time con techo de mínimo privilegio (§20, AUD-027)
│   ├── verification/        # VerificationGuard, restaurador de protected_paths y manifest (§13)
│   ├── worker/              # WorkerLoop con ToolBroker y generador de parches atómicos (§10)
│   ├── worktree/            # Gestor de git worktrees efímeros y MergeController serializado (§11, §16)
│   └── cli.py               # Punto de entrada unificado de comandos de consola
├── tests/                   # 31 suites de pruebas automatizadas unitarias, de integración y adversariales
└── docs/                    # Especificación arquitectónica v2.1 y auditorías formales
```

---

## Calidad de Código y Validación

El proyecto aplica controles de calidad rigurosos y obligatorios en cada cambio:

```bash
# 1. Ejecución de la suite completa de pruebas (133 tests)
uv run pytest

# 2. Análisis estático de tipos con tipado estricto
uv run mypy src tests

# 3. Linter y formateador de código
uv run ruff check .
```

Estado actual del control de calidad:
- **Pytest:** `133/133 passed` (0 fallos).
- **Mypy:** `Success: no issues found in 127 source files` bajo `--strict`.
- **Ruff:** `All checks passed!` (0 advertencias).

---

## Licencia

Distribuido bajo la Licencia MIT. Consulta el archivo `LICENSE` para más información.
