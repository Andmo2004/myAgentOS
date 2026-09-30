# Agentic OS — Feature Spec: Project Continuation & Existing Repository Audit

**Propuesta:** v1.0  
**Destino:** incorporación posterior a `agentic-os-v2.1.md` como extensión v2.2  
**Prioridad propuesta:** P1  
**Estado:** especificación propuesta, no implementada  
**Objetivo:** permitir que Agentic OS entre en un proyecto ya existente, reconstruya su estado operativo, detecte problemas verificables y genere un paquete de contexto accionable para continuar el desarrollo sin depender de una conversación previa.

---

## 1. Motivo de la característica

La arquitectura actual está muy bien orientada a resolver **una tarea concreta** de desarrollo mediante:

```text
routing
→ planificación
→ contexto mínimo suficiente
→ worker
→ sandbox
→ verificación
→ review
→ merge
```

Sin embargo, cuando Agentic OS entra por primera vez en un repositorio existente, falta una operación previa distinta de `DOC_LOOKUP`:

```text
"Necesito entender dónde estoy,
qué funciona,
qué está roto,
qué decisiones ya existen,
qué no debo tocar,
y qué tendría sentido hacer después."
```

`DOC_LOOKUP` recupera conocimiento persistente, mientras que esta nueva función debe reconstruir el **estado real del repositorio** a partir de Git, estructura, código, configuración, dependencias, tooling, documentación y resultados de diagnóstico.

La característica propuesta se denomina:

> **Project Continuation Audit (PCA)**

y su resultado principal es un:

> **Continuation Context Pack (`CONTINUATION_CONTEXT`)**

El pack permite que una segunda tarea se inicie sin volver a descubrir todo el proyecto desde cero.

---

# 2. Principios de diseño

La característica debe respetar los principios ya establecidos por Agentic OS.

### 2.1 Read-only por defecto

Un PCA no modifica el proyecto del usuario.

No genera parches, no hace merge y no altera tests, configuración ni documentación.

### 2.2 Hechos primero, redacción después

La máquina debe extraer primero hechos deterministas:

```text
Git
→ estructura
→ símbolos
→ dependencias
→ configuración
→ tests
→ diagnósticos
→ evidencias
```

Después un agente redacta la explicación humana.

El agente no debe inventar el estado del repositorio.

### 2.3 El diagnóstico no es el mismo concepto que un fallo del job

Los `FailureCode` de §14 describen fallos de ejecución del propio Agentic OS.

PCA necesita otro enum:

```text
FindingCode
```

que describa problemas encontrados **en el proyecto auditado**.

Esto evita mezclar:

```text
"el sandbox falló"
```

con:

```text
"el proyecto falla al ejecutar sus tests"
```

### 2.4 Cada afirmación importante debe tener evidencia

La salida debe diferenciar:

```text
OBSERVED
DERIVED
INFERRED
PROPOSED
UNKNOWN
```

Un agente no debe presentar una inferencia como si fuera un hecho observado.

### 2.5 El contexto de continuidad debe caducar

El contexto se vincula a un snapshot y, como mínimo, a:

```text
repository
base_commit
working_tree_hash
lockfile_hashes
toolchain_fingerprint
policy_version
```

Si cambia el repositorio de forma relevante, el pack pasa a `STALE`.

### 2.6 No convertir el primer escaneo en una ejecución sin límites

El audit debe tener dos niveles:

```text
STATIC
DYNAMIC
```

El modo `STATIC` no ejecuta el proyecto.

El modo `DYNAMIC` ejecuta diagnósticos autorizados dentro del Code Sandbox.

---

# 3. Nueva intención de routing

Añadir una intención:

```text
PROJECT_CONTINUATION
```

### Significado

Solicitudes equivalentes a:

```text
/continue
/audit-project
/onboard
"analiza este proyecto y dime cómo continuar"
"entra en este repo y explícame su estado"
"revisa lo que ya existe y detecta problemas"
"prepara el contexto para seguir desarrollando"
```

### Rama

```text
PROJECT_CONTINUATION
    ↓
PROJECT_AUDIT_RUN
```

No debe enrutarse a `DOC_LOOKUP`, porque el resultado es una **evaluación del estado del código**, no una simple recuperación de memoria.

---

# 4. Nueva capacidad del sistema

Se introduce el rol:

```text
continuity_analyst
```

Responsabilidad:

> convertir evidencia estructurada del repositorio en un contexto de continuidad legible y accionable.

Capacidades:

```text
structured_output
summarization
code_understanding
diagnostic_synthesis
```

### Restricciones

`continuity_analyst`:

- no escribe en el repositorio;
- no ejecuta herramientas;
- no concede permisos;
- no cambia el nivel de riesgo;
- no altera findings;
- no puede convertir `UNKNOWN` en `OBSERVED`;
- recibe únicamente la evidencia autorizada por el Job Controller.

El agente **redacta**; los componentes deterministas **descubren** y **validan**.

---

# 5. Capability Token de PCA

El modo de auditoría obtiene un token específico:

```yaml
capability:
  mode: project_continuation

  read:
    - "<repository namespace>/**"

  write: []

  execute:
    - "configured_static_analysis"
    - "configured_test_commands"
    - "configured_build_commands"
    - "configured_metadata_commands"

  network:
    mode: none
```

No se concede acceso de escritura.

Para el modo dinámico:

```text
execute ≠ acceso libre a shell
```

Solo se pueden ejecutar comandos incluidos en la política del proyecto.

---

# 6. Máquina de estados

## 6.1 Flujo

```text
IDLE
  ↓
ROUTING
  ├── PROJECT_CONTINUATION
  │       ↓
  │   DATA_CLASSIFY
  │       ↓
  │   PROJECT_SNAPSHOT
  │       ↓
  │   STATIC_DISCOVERY
  │       ↓
  │   DYNAMIC_DIAGNOSTICS (opcional)
  │       ↓
  │   FINDING_CLASSIFICATION
  │       ↓
  │   CONTINUATION_SYNTHESIS
  │       ↓
  │   CONTINUATION_REPORT_READY
  │       ↓
  │   COMPLETE
  │
  └── resto de intenciones actuales
```

### 6.2 Estados nuevos

```text
PROJECT_SNAPSHOT
STATIC_DISCOVERY
DYNAMIC_DIAGNOSTICS
FINDING_CLASSIFICATION
CONTINUATION_SYNTHESIS
CONTINUATION_REPORT_READY
```

### 6.3 No existe `WAIT_APPROVAL` para la escritura

Por defecto PCA es de solo lectura.

Sí puede existir:

```text
WAIT_DATA_APPROVAL
```

cuando la política de datos requiera autorización para enviar determinados contenidos al modelo remoto.

La aprobación de datos sigue estando gobernada por §18.

---

# 7. Snapshot del proyecto

Antes de analizar, el Job Controller crea un snapshot lógico.

```yaml
project_snapshot:
  snapshot_id:
  repository:
  base_commit:
  branch:
  working_tree:
    clean:
    content_hash:
  submodules:
  git_remotes:
  project_size:
  tracked_files:
  ignored_files:
  generated_files:
  toolchain_fingerprint:
  dependency_lock_hashes:
  policy_version:
```

### Regla

El snapshot es inmutable para ese job.

Todas las observaciones posteriores se refieren al snapshot concreto.

---

# 8. Pipeline de descubrimiento

## 8.1 Git

Extraer:

```text
branch actual
HEAD
estado clean/dirty
commits recientes
tags
remotes
submodules
uncommitted changes
stashes relevantes
```

No debe asumirse que `main` es la rama de trabajo correcta.

El documento debe indicar explícitamente:

```text
base_commit
current_branch
working_tree_status
```

---

## 8.2 Estructura del repositorio

El Context Compiler construye un mapa:

```text
tree
languages
frameworks
entrypoints
packages
modules
tests
docs
infrastructure
configuration
generated artifacts
```

Ejemplo:

```yaml
structure:
  languages:
    python: 0.74
    typescript: 0.26

  frameworks:
    - fastapi
    - pytest

  entrypoints:
    - src/app/main.py

  tests:
    - tests/unit/**
    - tests/integration/**

  docs:
    - README.md
    - docs/**

  infrastructure:
    - Dockerfile
    - compose.yaml
```

Los porcentajes son métricas de análisis y no deben presentarse como hechos si el detector no puede justificarlos.

---

# 9. Arquitectura reconstruida

El Context Compiler debe generar un `ARCHITECTURE_MAP`.

```yaml
architecture:
  modules:
    - id:
      path:
      purpose:
      public_symbols:
      dependencies:
      dependents:

  entrypoints:
    - path:
      symbol:

  external_dependencies:
    - package:
      version:
      usage_paths:

  internal_dependencies:
    - from:
      to:
```

La herramienta no debe intentar inventar una arquitectura conceptual cuando solo dispone de evidencias estructurales.

Por eso cada elemento puede incluir:

```yaml
evidence:
  source:
  anchor:
  confidence:
```

---

# 10. Baseline del proyecto

PCA debe responder a la pregunta:

> "¿Qué estado tiene el proyecto antes de que Agentic OS haga cualquier cambio?"

Debe recoger, cuando exista:

```text
compile
type check
lint
unit tests
integration tests
build
package validation
security scans
```

La ejecución debe producir un baseline:

```yaml
baseline:
  command:
  exit_code:
  duration_ms:
  status:
  stdout_hash:
  stderr_hash:
  structured_result:
```

Los logs completos pueden seguir la política de retención de §24.

---

# 11. Descubrimiento estático

El escaneo estático debe buscar, como mínimo:

```text
TODO
FIXME
XXX
HACK
deprecations
unreachable code
dead modules
unused dependencies
broken imports
missing symbols
duplicate configuration
configuration drift
documentation drift
test gaps detectables
unsafe defaults
hard-coded credentials detectables
deprecated APIs
inconsistent versions
```

No todo hallazgo textual es necesariamente un error.

Por ello el sistema debe producir:

```text
finding
+
evidence
+
confidence
```

---

# 12. Diagnóstico dinámico

El modo dinámico es opcional:

```bash
myagentos continue --dynamic
```

El agente puede ejecutar el baseline del proyecto y herramientas declaradas por la política.

El flujo es:

```text
PROJECT_SNAPSHOT
      ↓
sandbox
      ↓
diagnostic commands
      ↓
structured results
      ↓
FindingCode
```

### Reglas

El proyecto se ejecuta:

- fuera del workspace editable del usuario;
- dentro del Code Sandbox;
- con `network none` por defecto;
- con los mismos controles de §11;
- sin acceso a secretos del host;
- sin escribir cambios persistentes.

---

# 13. Modelo de Findings

## 13.1 Finding

```yaml
finding:
  finding_id:
  code:
  severity:
  status:
  title:
  summary:

  evidence:
    - kind:
      source:
      command:
      anchor:
      observed_value:
      expected_value:

  impact:
  reproducibility:
  confidence:

  introduced_in:
  last_verified_at:

  proposed_actions:
    - id:
      description:
      prerequisites:
      validation:
```

---

## 13.2 Enum `FindingCode`

```text
BUILD_FAILURE
TEST_FAILURE
TYPECHECK_FAILURE
LINT_FAILURE

BROKEN_IMPORT
MISSING_SYMBOL
DEPENDENCY_CONFLICT
DEPENDENCY_OUTDATED
LOCKFILE_DRIFT

CONFIGURATION_ERROR
ENVIRONMENT_MISMATCH
DOC_DRIFT
ARCHITECTURE_DRIFT

SECURITY_EXPOSURE
SECRET_DETECTED
UNSAFE_DEFAULT

DEAD_CODE
DUPLICATED_LOGIC
MISSING_TEST_COVERAGE_SIGNAL

GIT_STATE_DIRTY
UNCOMMITTED_CHANGE
STALE_GENERATED_ARTIFACT

UNKNOWN
```

Este enum es extensible por versión, pero cerrado dentro de una versión concreta del contrato.

---

# 14. Severidad del finding

La severidad del finding describe el problema observado, no el riesgo del cambio.

```text
BLOCKER
HIGH
MEDIUM
LOW
INFO
```

No debe confundirse con:

```text
RISK_FINAL
RISK_DIFF
```

Ejemplo:

```text
Finding:
  code: TEST_FAILURE
  severity: HIGH

Proposed future fix:
  risk_level: MEDIUM
```

El hecho de que un fallo sea grave no significa automáticamente que la solución tenga el mismo `RiskLevel`.

---

# 15. Evidencia y confianza

Cada finding debe distinguir:

### `OBSERVED`

Directamente producido por una herramienta.

Ejemplo:

```text
pytest exit code = 1
```

### `DERIVED`

Conclusión determinista sobre datos observados.

Ejemplo:

```text
un módulo importado no existe
```

### `INFERRED`

Interpretación del `continuity_analyst`.

Ejemplo:

```text
parece existir una migración incompleta
```

### `PROPOSED`

Acción sugerida.

Ejemplo:

```text
consolidar dos adaptadores antes de añadir nuevas funciones
```

### `UNKNOWN`

Información que todavía no puede establecerse.

La redacción final debe conservar estas etiquetas cuando sean relevantes.

---

# 16. Agente de continuidad

El `continuity_analyst` recibe:

```text
PROJECT_SNAPSHOT
ARCHITECTURE_MAP
BASELINE
FINDINGS
PROJECT_DOCUMENTS autorizados
ADR activos
KNOWLEDGE_CONTEXT relevante
GIT_METADATA
```

No recibe:

```text
scratchpads
chain-of-thought
intentos internos del Worker
credenciales
secretos
permisos no concedidos
contenido fuera de scope
```

---

# 17. Contrato de salida del agente

El LLM devuelve un objeto estructurado:

```yaml
continuation_report:
  summary:
  current_state:
  architecture:
  working_area:
  known_good:
  known_broken:

  findings:
    - finding_id:
      explanation:
      impact:
      evidence_refs:

  blockers:
    - finding_id:

  unresolved_questions:
    - question:
      reason:

  recommended_next_steps:
    - step_id:
      title:
      objective:
      prerequisites:
      affected_paths:
      risk_hint:
      validation:
      depends_on:

  do_not_touch_yet:
    - path:
      reason:

  suggested_first_task:
    objective:
    scope:
    validation:

  context_digest:
```

El `context_digest` lo calcula el controlador, no el LLM.

---

# 18. Qué debe responder el `CONTINUATION_CONTEXT`

El documento generado debe contestar, de forma explícita, estas preguntas:

```text
1. ¿Qué proyecto es este?
2. ¿En qué commit se encuentra?
3. ¿Qué estado tiene Git?
4. ¿Cómo está estructurado?
5. ¿Cuáles son sus entrypoints?
6. ¿Qué módulos dependen de cuáles?
7. ¿Cómo se ejecuta?
8. ¿Cómo se prueba?
9. ¿Qué funciona actualmente?
10. ¿Qué falla actualmente?
11. ¿Qué errores son reproducibles?
12. ¿Cuáles son los principales bloqueos?
13. ¿Qué decisiones arquitectónicas ya están activas?
14. ¿Qué rutas son sensibles?
15. ¿Qué información es desconocida?
16. ¿Qué debería investigarse antes de modificar código?
17. ¿Qué pasos concretos permiten continuar?
18. ¿Cómo se validaría cada siguiente paso?
19. ¿Qué NO debería tocarse todavía?
20. ¿Qué contexto debe reutilizarse en el próximo job?
```

---

# 19. Formato de `CONTINUATION_CONTEXT.md`

El artefacto humano debe tener una estructura estable:

```markdown
# Project Continuation Context

## Snapshot

- Repository:
- Commit:
- Branch:
- Working tree:
- Generated at:
- Context version:
- Context hash:

## Executive Summary

...

## Project Shape

### Stack

...

### Entrypoints

...

### Module Map

...

## Current Operational State

### Build

...

### Tests

...

### Type Checking

...

### Lint

...

## Findings

### BLOCKER

...

### HIGH

...

### MEDIUM

...

### LOW / INFO

...

## Architecture and Constraints

...

## Known Good

...

## Known Broken

...

## Unknowns

...

## Recommended Continuation

### Step 1

...

### Step 2

...

### Step 3

...

## Do Not Touch Yet

...

## Suggested First Job

...

## Evidence

...
```

---

# 20. Paquete de continuidad persistente

No debe depender únicamente de Markdown.

El job genera:

```text
.myagentos/
└── projects/
    └── <project_id>/
        └── continuity/
            └── <snapshot_id>/
                ├── snapshot.json
                ├── architecture.json
                ├── baseline.json
                ├── findings.json
                ├── continuation_report.json
                ├── CONTINUATION_CONTEXT.md
                └── manifest.json
```

### Regla

El Markdown es la interfaz humana.

Los JSON son el contrato de máquina.

---

# 21. Persistencia y Git

PCA no debe escribir automáticamente:

```text
README.md
docs/**
ADR/**
```

ni modificar archivos del proyecto.

Por defecto los artefactos viven bajo:

```text
.myagentos/projects/<project_id>/continuity/
```

Puede existir una segunda operación explícita:

```bash
myagentos continue --write-project-context
```

que cree un documento versionable dentro del repositorio.

Esta segunda operación debe convertirse en un job de escritura normal y pasar por:

```text
PLAN
→ RISK
→ CAPABILITY
→ PATCH
→ VERIFY
→ REVIEW
```

PCA puro sigue siendo read-only.

---

# 22. Reutilización en trabajos posteriores

Cuando el usuario cree una nueva tarea:

```text
"añade soporte para X"
```

el Context Compiler puede recuperar:

```text
latest valid CONTINUATION_CONTEXT
```

si:

```text
context.base_commit == current base
```

y:

```text
context freshness == valid
```

En caso contrario:

```text
STALE CONTINUATION_CONTEXT
        ↓
incremental PCA
        ↓
new context digest
```

No hace falta volver a analizar el repositorio completo si puede demostrarse que solo cambió una parte del dependency closure.

---

# 23. Incremental Continuation Audit

La segunda ejecución debe ser más barata que la primera cuando sea posible.

Ejemplo:

```text
PCA #1
  snapshot A

repo changes

PCA #2
  snapshot B
      ↓
git diff A..B
      ↓
affected modules
      ↓
affected findings
      ↓
revalidate only impacted diagnostics
```

Esto encaja directamente con la filosofía de:

> mínimo contexto suficiente.

---

# 24. Staleness

Cada artefacto lleva:

```yaml
freshness:
  generated_at:
  base_commit:
  working_tree_hash:
  dependency_hash:
  architecture_hash:
  policy_version:
```

El reporte se marca:

```text
VALID
STALE
SUPERSEDED
```

Pasa a `STALE` cuando una modificación afecta:

```text
scope del finding
dependency closure
entrypoints
toolchain
lockfiles
configuración relevante
ADR/constraints aplicados
```

---

# 25. Detección de errores: evitar falsas alarmas

El objetivo no es maximizar el número de findings.

Se debe minimizar:

```text
false_positive finding
```

Por eso:

```text
finding detectado
    ↓
¿tiene evidencia?
    ├── no → UNKNOWN / no emitir
    └── sí
         ↓
¿es reproducible?
    ├── sí → confidence alta
    └── no → marcar reproducibilidad limitada
```

El LLM puede explicar un finding, pero no debe inventarlo.

---

# 26. Priorización de cómo continuar

El sistema debe generar orden de ejecución por **dependencias**, no solo por texto.

Cada paso propone:

```yaml
continuation_step:
  step_id:
  objective:
  prerequisites:
  affected_findings:
  affected_paths:
  expected_output:
  validation:
  estimated_scope:
```

Ejemplo conceptual:

```text
F-001 build roto
    ↓
STEP-001 reparar configuración de entorno
    ↓
baseline vuelve a verde
    ↓
STEP-002 ejecutar tests
    ↓
F-007 pasa a ser reproducible
    ↓
STEP-003 reparar módulo
```

Esto crea una cadena accionable:

```text
estado actual
→ bloqueo
→ resolución
→ nueva evidencia
→ siguiente decisión
```

---

# 27. `Suggested First Job`

El reporte debe terminar con una propuesta de tarea inicial, pero **no debe ejecutarla automáticamente**.

Ejemplo:

```yaml
suggested_first_job:
  intent: PLANNED_CODE
  objective: "Resolver el bloqueo de configuración de entorno"
  scope:
    - src/config/**
    - tests/config/**
  prerequisites:
    - "confirmar variable X"
  acceptance:
    - "baseline de tests vuelve a estado conocido"
  risk_hint: MEDIUM
```

El Job Controller debe tratarlo como una nueva solicitud planificable, no como una autorización implícita.

---

# 28. Integración con `DOC_LOOKUP`

Las dos capacidades deben complementarse:

```text
DOC_LOOKUP
  = "¿qué conocimiento persistente existe?"

PROJECT_CONTINUATION
  = "¿cuál es el estado real actual del proyecto?"

```

PCA puede usar `DOC_LOOKUP` como fuente adicional:

```text
Git/code
+
ADR
+
project KB
+
previous continuation context
=
continuation pack
```

Pero la memoria no debe prevalecer sobre el estado real del repositorio cuando exista contradicción.

Ejemplo:

```text
ADR dice:
  "módulo X es el entrypoint"

Git/code muestra:
  "módulo Y es el entrypoint actual"

Resultado:
  DOC_DRIFT / ARCHITECTURE_DRIFT
```

El sistema no debe ocultar la discrepancia.

---

# 29. Eventos de auditoría

Añadir al catálogo de eventos:

```text
PROJECT_SNAPSHOT_CREATED
STATIC_DISCOVERY_STARTED
STATIC_DISCOVERY_COMPLETED

DYNAMIC_DIAGNOSTICS_STARTED
DYNAMIC_DIAGNOSTICS_COMPLETED

FINDING_DETECTED
FINDING_CLASSIFIED

CONTINUATION_SYNTHESIS_STARTED
CONTINUATION_REPORT_CREATED

CONTINUATION_CONTEXT_VALIDATED
CONTINUATION_CONTEXT_STALE
```

Ejemplo:

```yaml
event:
  type: FINDING_DETECTED
  job_id:
  snapshot_id:
  finding_id:
  finding_code:
  severity:
  evidence_hash:
```

---

# 30. Observabilidad

Extender §25:

```yaml
continuation:
  snapshot_id:
  snapshot_hash:

  files_scanned:
  symbols_indexed:
  diagnostics_run:
  findings_count:

  findings_by_code:
  findings_by_severity:

  continuation_context_hash:

  stale_reason:
  reused_previous_context:
```

Métricas:

```text
time_to_context_ready
tokens_to_context_ready
finding_precision
finding_recurrence
baseline_reproducibility
context_reuse_rate
stale_context_rate
time_to_first_successful_followup_job
```

La métrica más importante de negocio de esta feature es:

> **tiempo desde abrir un repositorio desconocido hasta completar con éxito la primera tarea real posterior al onboarding.**

---

# 31. Contratos de integridad

El controlador debe sellar:

```text
snapshot_hash
architecture_hash
baseline_hash
findings_hash
continuation_report_hash
context_hash
```

El LLM nunca calcula estos hashes.

La cadena debe quedar registrada en el Audit Trail.

---

# 32. Seguridad

PCA trata el repositorio como:

```text
UNTRUSTED
```

incluyendo:

```text
README
comments
issues
docs
scripts
config
source code
dependencies
```

El contenido puede incluir prompt injection.

Por tanto:

```text
repository content
    ↓
trusted deterministic extractor
    ↓
structured evidence
    ↓
continuity_analyst
```

El texto extraído del proyecto jamás puede:

```text
conceder permisos
activar herramientas
pedir secretos
modificar policy
cambiar risk level
```

---

# 33. Preservación de secretos

Durante PCA:

```text
secret detection
    ↓
redaction
    ↓
data classification
    ↓
Model Gateway
```

Un secreto detectado:

```text
.env
API_KEY
private key
credential file
token
```

no se entrega al `continuity_analyst`.

El finding conserva:

```yaml
code: SECRET_DETECTED
evidence:
  path:
  detector:
  fingerprint:
```

pero no el valor secreto.

---

# 34. Qué NO debe hacer esta feature

PCA no debe:

```text
- corregir errores automáticamente
- cambiar dependencias
- actualizar lockfiles
- borrar código muerto
- reescribir documentación
- crear ADRs canónicos
- cambiar configuración
- hacer commits
- hacer merge
- pedir al usuario permiso para algo que no requiere escritura
- convertir recomendaciones en tareas ejecutadas automáticamente
```

Su responsabilidad termina en:

```text
entender
+
diagnosticar
+
explicar
+
preparar la siguiente acción
```

---

# 35. CLI propuesta

### Auditoría estática

```bash
myagentos continue
```

### Auditoría con diagnóstico dinámico

```bash
myagentos continue --dynamic
```

### Ver reporte

```bash
myagentos continue report
```

### Forzar regeneración

```bash
myagentos continue refresh
```

### Inspeccionar findings

```bash
myagentos continue findings
```

### Crear contexto versionable en el proyecto

```bash
myagentos continue --write-project-context
```

La última opción genera un job de escritura gobernado; no es una excepción de seguridad.

---

# 36. Ejemplo de experiencia de usuario

Entrada:

```text
$ myagentos continue --dynamic
```

Salida conceptual:

```text
Agentic OS — Project Continuation Audit

Repository: my-project
Branch: main
Commit: 7c31f2e
Working tree: DIRTY

Stack:
  Python 3.12
  FastAPI
  PostgreSQL
  pytest

Baseline:
  compile      PASS
  typecheck    FAIL
  lint         PASS
  unit tests   FAIL (4)
  integration  NOT RUN

Findings:
  BLOCKER  F-001 TYPECHECK_FAILURE
  HIGH     F-002 TEST_FAILURE
  HIGH     F-003 DEPENDENCY_CONFLICT
  MEDIUM   F-004 DOC_DRIFT

Recommended continuation:
  1. Resolve F-001
  2. Re-run baseline
  3. Reproduce F-002
  4. Resolve dependency conflict
  5. Reconcile documentation

Context:
  CONTINUATION_CONTEXT.md
```

El sistema todavía no modifica nada.

---

# 37. Prompt conceptual del `continuity_analyst`

El prompt debe ser esencialmente un contrato de transformación:

```text
You are the continuity analyst.

Your task is to transform repository evidence into a continuation context.

Rules:
1. Never invent repository facts.
2. Every substantive claim must reference an evidence item.
3. Distinguish observed facts from inference.
4. Preserve unknowns.
5. Do not propose permissions.
6. Do not propose secrets.
7. Do not modify policy.
8. Do not claim a fix has been applied.
9. Prefer exact paths, symbols and commands.
10. Produce structured output matching the schema.
```

El prompt no convierte al modelo en autoridad.

---

# 38. Relación con `KNOWLEDGE_CONTEXT`

Los tres conceptos deben quedar separados:

```text
KNOWLEDGE_CONTEXT
  = memoria persistente del proyecto

CONTINUATION_CONTEXT
  = fotografía operativa del estado actual

WORKER_CONTEXT
  = contexto mínimo suficiente para una tarea concreta
```

La relación ideal:

```text
KNOWLEDGE_CONTEXT
       +
CONTINUATION_CONTEXT
       +
request
       ↓
Context Compiler
       ↓
WORKER_CONTEXT
```

Esto evita que el Worker tenga que leer todo el repositorio otra vez.

---

# 39. Relación con errores históricos

El sistema debe conservar historial de findings.

Ejemplo:

```yaml
finding_history:
  finding_id: F-002

  first_seen:
    commit: A

  last_seen:
    commit: B

  occurrences:
    - commit: A
      status: OPEN
    - commit: B
      status: OPEN
```

Cuando una futura auditoría encuentre el mismo problema:

```text
existing finding
+
new evidence
```

en vez de crear un finding completamente nuevo.

---

# 40. Estados de un finding

```text
OPEN
ACKNOWLEDGED
IN_PROGRESS
RESOLVED
REOPENED
WONT_FIX
STALE
UNKNOWN
```

El cambio de estado debe estar respaldado por evidencia.

Una nota generada por un LLM no puede marcar por sí sola un finding como `RESOLVED`.

---

# 41. Resolución por un job posterior

Cuando una nueva tarea modifica el repositorio:

```text
PCA finding F-002
       ↓
PLANNED_CODE job
       ↓
Patch
       ↓
Verify
       ↓
Finding re-check
       ↓
F-002 RESOLVED
```

La resolución debe basarse en una nueva comprobación determinista.

---

# 42. Integración en el benchmark

El benchmark de §26 debe añadir un conjunto específico para PCA.

### Dataset

```text
repositorios previamente desarrollados
repositorios con tests rotos
repositorios con documentación desactualizada
repositorios con dependencias inconsistentes
repositorios con deuda técnica
repositorios con código correcto pero memoria incompleta
```

### Métricas

```text
finding precision
finding recall
baseline reproducibility
context completeness
context token cost
time to first successful task
stale report detection
duplicate finding rate
```

El objetivo no debe ser encontrar "muchos" problemas, sino producir findings útiles y verificables.

---

# 43. Criterios de aceptación

La feature se considera implementada cuando puede demostrar:

```text
1. Detectar y registrar el commit exacto del snapshot.
2. Reconstruir la estructura del repositorio sin LLM.
3. Detectar el stack y los entrypoints con evidencia.
4. Ejecutar baseline en sandbox cuando se solicita --dynamic.
5. Generar findings estructurados.
6. Diferenciar findings de FailureCode.
7. Generar CONTINUATION_CONTEXT.md.
8. Generar continuation_report.json.
9. Cada afirmación sustantiva tiene una referencia de evidencia.
10. El LLM no puede modificar el repositorio.
11. El contexto se marca STALE cuando cambia el scope relevante.
12. Una segunda tarea puede consumir el contexto sin rehacer el descubrimiento completo.
13. Los hashes del snapshot y del contexto los calcula el controlador.
14. Los secretos no aparecen en el informe ni en el prompt del analista.
15. El sistema no transforma recomendaciones en cambios automáticamente.
```

---

# 44. Plan de implementación

## P1.1 — Project Snapshot

Implementar:

```text
src/myagentos/continuity/snapshot.py
src/myagentos/continuity/models.py
tests/test_continuity_snapshot.py
```

Responsabilidad:

```text
Git + working tree + hashes + fingerprint
```

---

## P1.2 — Static Discovery

Implementar:

```text
src/myagentos/continuity/discovery.py
src/myagentos/continuity/findings.py
tests/test_continuity_discovery.py
```

Primera versión:

```text
tree scan
imports
symbols
entrypoints
dependency files
test layout
TODO/FIXME
config drift básico
```

---

## P1.3 — Dynamic Diagnostics

Reutilizar:

```text
Code Sandbox
Tool Broker
Verification Guard
```

pero en un modo:

```text
diagnostic-only
```

No debe aplicarse `PatchSet`.

---

## P1.4 — Continuity Analyst

Añadir al Model Registry:

```text
continuity_analyst
```

Implementar:

```text
src/myagentos/continuity/synthesizer.py
tests/test_continuity_synthesizer.py
```

Salida:

```text
continuation_report.json
CONTINUATION_CONTEXT.md
```

---

## P1.5 — Persistencia e incrementalidad

Implementar:

```text
src/myagentos/continuity/store.py
src/myagentos/continuity/freshness.py
```

Objetivo:

```text
reutilizar contexto
+
detectar stale
+
reanalizar solo lo afectado
```

---

## P1.6 — CLI

Añadir:

```text
myagentos continue
myagentos continue --dynamic
myagentos continue report
myagentos continue findings
```

---

## P1.7 — Integración con Context Compiler

La nueva fuente de contexto pasa a ser:

```text
CONTINUATION_CONTEXT
```

y debe entrar en el compilador antes de producir:

```text
PLAN_CONTEXT
WORKER_CONTEXT
```

---

# 45. Cambios requeridos en `agentic-os-v2.1.md`

Cuando esta propuesta se acepte, la v2.2 debería actualizar como mínimo:

### §3 Glosario

Añadir:

```text
Continuity Analyst
Project Snapshot
Finding
Continuation Context
```

### §6 Routing

Añadir:

```text
PROJECT_CONTINUATION
```

### §8 FSM

Añadir:

```text
PROJECT_SNAPSHOT
STATIC_DISCOVERY
DYNAMIC_DIAGNOSTICS
FINDING_CLASSIFICATION
CONTINUATION_SYNTHESIS
CONTINUATION_REPORT_READY
```

### §9 Context Compiler

Añadir:

```text
CONTINUATION_CONTEXT
```

### §14 Fallos

Mantener `FailureCode` intacto y añadir una sección independiente:

```text
Project Findings
```

### §17 Model Registry

Añadir:

```text
continuity_analyst
```

### §24 Eventos

Añadir los eventos de §29.

### §25 Observabilidad

Añadir telemetría de continuidad.

### §26 Benchmark

Añadir benchmark específico de onboarding/continuity.

### §27 Criterios de aceptación

Añadir bloque de Project Continuation.

### §28 Priorización

Situar PCA después de:

```text
Context Compiler
Failure Classifier
Context Expansion
```

o fusionarlo con esa misma fase P1 cuando exista el pipeline base.

---

# 46. Decisión arquitectónica nueva

### D11 — El estado del repositorio debe ser recuperable como un contexto de continuidad verificable

Agentic OS no debe obligar a cada tarea nueva a reconstruir desde cero el estado de un proyecto existente.

Debe existir una separación entre:

```text
memoria histórica
KNOWLEDGE_CONTEXT

estado operativo actual
CONTINUATION_CONTEXT

contexto puntual de una tarea
WORKER_CONTEXT
```

El `CONTINUATION_CONTEXT` debe ser:

```text
versionado
anclado a commit
basado en evidencia
reutilizable
invalidable
read-only por defecto
```

Y su propósito debe ser explícitamente:

```text
reducir el coste de volver a entender un proyecto
sin ocultar los errores que ya existen.
```

---

# 47. Flujo completo resultante

La nueva arquitectura queda:

```text
                         ┌───────────────────────┐
                         │  Usuario / CLI / IDE  │
                         └───────────┬───────────┘
                                     ↓
                              ┌─────────────┐
                              │   Routing   │
                              └──────┬──────┘
                                     │
                  ┌──────────────────┼───────────────────┐
                  │                  │                   │
                  ▼                  ▼                   ▼
            PLANNED_CODE     PROJECT_CONTINUATION   DOC_LOOKUP
                  │                  │                   │
                  │                  ▼                   │
                  │          PROJECT_SNAPSHOT            │
                  │                  │                   │
                  │                  ▼                   │
                  │          STATIC_DISCOVERY            │
                  │                  │                   │
                  │                  ▼                   │
                  │       DYNAMIC_DIAGNOSTICS            │
                  │                  │                   │
                  │                  ▼                   │
                  │        FINDING_CLASSIFICATION        │
                  │                  │                   │
                  │                  ▼                   │
                  │      CONTINUATION_SYNTHESIS          │
                  │                  │                   │
                  │                  ▼                   │
                  │       CONTINUATION_CONTEXT           │
                  │                  │                   │
                  └──────────────────┼───────────────────┘
                                     ▼
                              Context Compiler
                                     │
                  ┌──────────────────┼──────────────────┐
                  ▼                  ▼                  ▼
            PLAN_CONTEXT       WORKER_CONTEXT     KNOWLEDGE_CONTEXT
```

La idea central es que **PCA se convierte en la puerta de entrada para un repositorio desconocido**, mientras que el resto del sistema se ocupa de ejecutar cambios sobre un estado ya comprendido y versionado.

---

# 48. Resumen de implementación

La implementación recomendada no sería:

```text
"crear un agente que lea todos los archivos y escriba un resumen"
```

Sería:

```text
snapshot determinista
        ↓
mapa estructural
        ↓
baseline reproducible
        ↓
findings deterministas
        ↓
evidencia estructurada
        ↓
Continuity Analyst
        ↓
Continuation Context Pack
        ↓
reutilización por Context Compiler
        ↓
siguiente job
```

La diferencia es importante: el agente no intenta ser la fuente de verdad del proyecto. La fuente de verdad sigue siendo el estado observable del repositorio y sus herramientas de validación; el agente convierte ese estado en una representación útil para que el desarrollo pueda continuar.
