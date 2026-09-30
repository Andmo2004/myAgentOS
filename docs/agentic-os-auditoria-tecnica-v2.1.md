# Agentic OS — Auditoría Técnica de la v2.1 y del estado de implementación

**Fecha de auditoría:** 2026-09-30  
**Base documental:** `agentic-os-v2.1.md` + `Se ha pegado el markdown.md`  
**Tipo:** auditoría de coherencia, madurez y brecha entre especificación e implementación  
**Estado:** diagnóstico técnico; no modifica la arquitectura ni propone la implementación de nuevas features

> **Alcance de esta auditoría:** revisar exclusivamente lo que ya existe en la especificación y en el registro de implementación proporcionado. La auditoría no sustituye una revisión del código fuente ejecutable. Las afirmaciones sobre pruebas pasadas, módulos creados o comandos ejecutados se consideran evidencia declarada en el registro de implementación, no una validación independiente realizada durante esta revisión.

---

# 1. Resumen ejecutivo

La v2.1 presenta una arquitectura con una tesis clara y consistente:

```text
routing local
→ riesgo
→ planificación
→ contexto mínimo suficiente
→ capabilities
→ ejecución aislada
→ verificación independiente
→ revisión
→ merge auditado
→ memoria post-merge
```

La decisión arquitectónica más importante está correctamente repetida en varias partes del documento:

```text
el LLM propone
los componentes deterministas deciden
```

La separación entre `Job Controller`, `Policy Engine`, `Context Compiler`, `Tool Broker`, `Verification Guard` y `Model Gateway` reduce las responsabilidades ambiguas y crea fronteras razonables entre inferencia, permisos, ejecución y persistencia.

La especificación también muestra un esfuerzo significativo por resolver problemas que normalmente quedan implícitos en sistemas agénticos:

- obsolescencia del plan;
- monotonicidad del riesgo;
- protección de tests;
- aislamiento del sandbox;
- herencia de `untrusted`;
- costes y reservas atómicas;
- ciclo de vida de proveedores;
- reproducibilidad;
- auditoría por eventos;
- memoria con staging y anclaje;
- benchmark antes de optimizar.

El registro de implementación indica que la base P0 ya incluye modelos de dominio, Event Store, FSM, Policy Engine, Router v0, worktrees, sandbox, Verification Guard, Model Gateway, benchmark y CLI, además de una ejecución declarada de `pytest`, `ruff` y `mypy`.

Por tanto, el principal problema actual **no es una falta de arquitectura**.

El principal problema es la transición entre:

```text
arquitectura bien especificada
```

y:

```text
sistema realmente funcional de extremo a extremo
```

La brecha más importante está alrededor de los componentes que el propio documento sitúa en P1:

```text
Context Compiler real
Worker + Tool Broker Loop
Failure Classifier operativo
Context Expansion
presupuesto/rate limiting/circuit breaker
Skills
Research
Independent Review LLM
memoria ejecutable
E2E con modelos reales
```

La auditoría detecta además varias áreas que conviene consolidar antes de seguir añadiendo superficie funcional:

1. Diferenciar con mayor precisión **especificación normativa**, **implementación actual** y **objetivos experimentales**.
2. Convertir varios contratos descritos en prosa en contratos formales ejecutables.
3. Completar la instrumentación E2E.
4. Separar completamente los errores del sistema (`FailureCode`) de los problemas descubiertos en un repositorio.
5. Definir de forma más precisa qué significa que un job esté realmente "completo".
6. Reducir las zonas donde una implementación podría cumplir el texto de una sección pero incumplir la intención global del sistema.

---

# 2. Fuentes y nivel de evidencia

La auditoría se basa en dos documentos.

## 2.1 Especificación arquitectónica

`agentic-os-v2.1.md`

Declara:

- arquitectura;
- topología;
- roles;
- FSM;
- riesgo;
- contexto;
- ejecución;
- sandbox;
- PatchSet;
- verificación;
- fallos;
- revisión;
- merge;
- Gateway;
- datos;
- amenazas;
- skills;
- research;
- memoria;
- auditoría;
- benchmarks;
- criterios de aceptación;
- roadmap.

La especificación establece expresamente que los valores de latencia, coste, ahorro de tokens, umbrales y tasas de regresión son objetivos o valores por defecto hasta ser validados experimentalmente.

## 2.2 Registro de implementación

`Se ha pegado el markdown.md`

El documento enumera módulos creados, comandos ejecutados y el estado declarado de las pruebas.

Entre los elementos indicados:

```text
core models
event_store
state_projector
FSM
policy
router
worktree
sandbox
verification
gateway
benchmark
CLI
```

El registro también declara:

```text
31 tests unitarios
ruff
mypy
pytest
commit inicial Git
benchmark
```

Esta auditoría acepta esas afirmaciones como evidencia documental, pero no las considera una ejecución independiente del código.

---

# 3. Evaluación de la tesis arquitectónica

## 3.1 Separación de autoridad

La arquitectura diferencia correctamente entre:

```text
LLM
    propone contenido

componentes deterministas
    deciden permisos
    deciden transiciones
    validan integridad
    aplican políticas
```

Esta decisión está reflejada especialmente en:

```text
Job Controller
Policy Engine
Tool Broker
Verification Guard
Model Gateway
```

### Evaluación

**Estado: sólido.**

Es una de las partes mejor definidas de la arquitectura y debería conservarse como principio transversal.

---

## 3.2 Risk-based governance

El modelo:

```text
RISK_PRELIMINARY
        ↓
RISK_FINAL
        ↓
RISK_DIFF
```

con regla:

```text
risk(N+1) >= risk(N)
```

es conceptualmente adecuado para evitar que una aprobación previa se reutilice cuando el cambio real se amplía.

### Evaluación

**Estado: sólido conceptualmente; requiere mayor validación E2E.**

El punto pendiente no es la definición del modelo, sino comprobar que todos los caminos reales del controlador respetan la monotonía y la invalidación de aprobaciones.

---

## 3.3 Contexto mínimo suficiente

La especificación no interpreta la optimización de tokens como "mandar menos archivos" sino como:

```text
mandar el mínimo contexto suficiente
```

La distinción entre:

```text
PLAN_CONTEXT
WORKER_CONTEXT
KNOWLEDGE_CONTEXT
```

es apropiada.

### Evaluación

**Estado: buena decisión arquitectónica; implementación pendiente.**

Es una de las partes que más influirá en el valor práctico del sistema y necesita benchmark real antes de afirmar mejoras de coste o latencia.

---

# 4. Fortalezas encontradas

## AUD-001 — Fronteras de responsabilidad claras

La nomenclatura elimina ambigüedades:

```text
Planner
Job Controller
Worker
Tool Broker
Policy Engine
Verification Guard
Independent Reviewer
Model Gateway
Curator
```

Además, la especificación evita el término genérico `Orchestrator`.

### Impacto

Reduce la posibilidad de que diferentes partes del sistema comiencen a tomar decisiones de autoridad superpuestas.

### Estado

**Correcto.**

---

# 5. Hallazgos de coherencia de especificación

## AUD-002 — La especificación es más avanzada que el estado implementado

La especificación describe una plataforma con una gran cantidad de capacidades P1/P2, mientras el registro de implementación muestra principalmente los fundamentos P0.

El propio registro declara como siguiente paso:

```text
Worker & Tool Broker Loop
Context Compiler
E2E con LLM real
```

### Riesgo

Existe el peligro de seguir extendiendo el documento más rápido que el runtime.

El resultado podría ser:

```text
specification maturity
        >
implementation maturity
```

y dificultar saber qué contratos están realmente probados.

### Acción

Introducir explícitamente tres estados para cada capacidad:

```text
SPECIFIED
IMPLEMENTED
VERIFIED
```

y, cuando proceda:

```text
EXPERIMENTAL
```

Ejemplo:

```yaml
component:
  name: Context Compiler
  specified: true
  implemented: false
  verified: false
```

### Prioridad

**Alta.**

---

## AUD-003 — P0/P1 necesita una definición operacional más estricta

La sección de priorización clasifica correctamente muchas piezas, pero algunas capacidades están descritas como P0/P1 mientras sus dependencias todavía no están completamente operativas.

Ejemplo:

```text
Verification Guard
```

puede estar implementado parcialmente sin que exista todavía todo el flujo E2E:

```text
Planner
→ Worker
→ Tool Broker
→ Patch
→ Policy
→ Verify
→ Review
→ Merge
```

### Riesgo

Un componente puede considerarse "hecho" aisladamente aunque el sistema todavía no complete una tarea real.

### Acción

Definir dos niveles:

```text
component acceptance
system acceptance
```

Un componente aprobado no implica que el sistema esté preparado para uso real.

### Prioridad

**Alta.**

---

# 6. Brecha entre especificación y runtime

## AUD-004 — Worker real aún pendiente

La especificación define:

```text
single_shot
tool_loop
read_file
search_symbols
run_command
propose_patch
request_context_expansion
```

pero el registro de implementación identifica explícitamente el:

```text
Worker & Tool Broker Loop
```

como siguiente paso.

### Conclusión

La arquitectura de ejecución está definida, pero el ciclo agéntico operativo todavía no aparece como una capacidad P0 completada en el registro.

### Acción

Antes de continuar con optimizaciones:

```text
request
→ router
→ plan
→ capability
→ worker
→ tool broker
→ patch
→ policy
→ verify
→ review
→ merge
```

debe funcionar en un repositorio de prueba real.

### Prioridad

**Crítica para el MVP funcional.**

---

## AUD-005 — Context Compiler real pendiente

La especificación declara Tree-sitter, dependency closure y construcción de contextos, pero el registro de implementación sitúa el Context Compiler como siguiente paso.

### Riesgo

Gran parte de la tesis de eficiencia del sistema todavía no puede evaluarse sobre la implementación real.

### Acción

Implementar primero una versión determinista mínima:

```text
repository tree
+
files
+
symbols
+
imports
+
tests
+
dependency manifests
```

y después:

```text
dependency closure
```

### Prioridad

**Crítica.**

---

## AUD-006 — E2E con LLM real todavía es una frontera pendiente

Los adaptadores de OpenAI y Gemini aparecen en el registro de implementación, incluyendo salida JSON estructurada, pero el propio documento marca como siguiente paso conectar un flujo E2E con un modelo real.

### Distinción importante

Tener:

```text
adapter
```

no equivale a tener:

```text
E2E production-like job
```

### Acción

Crear un test E2E mínimo que compruebe:

```text
CLI
→ Controller
→ Router
→ Gateway
→ Planner
→ Worker
→ Tool Broker
→ Sandbox
→ Verification
→ Merge
→ Audit Trail
```

### Prioridad

**Crítica.**

---

# 7. Riesgo y gobernanza

## AUD-007 — El modelo de riesgo está bien definido, pero necesita pruebas de propiedades

La especificación exige monotonía y vínculos entre:

```text
approval
base_commit
scope_hash
risk_level
policy_version
```

### Riesgo

Las propiedades de seguridad pueden romperse por una combinación no prevista de estados aunque cada clase individual funcione correctamente.

### Acción

Añadir pruebas de propiedades:

```text
risk never decreases
approval becomes invalid when required
patch cannot exceed capability
stale plan is detected
protected paths remain protected
```

### Prioridad

**Alta.**

---

## AUD-008 — Falta una matriz explícita de invariantes globales

Hay invariantes distribuidos por muchas secciones.

Ejemplos:

```text
no secret egress
no unauthorized write
no policy downgrade
no unprotected test mutation
no merge without required approval
no post-approval scope expansion
```

### Problema

La documentación los define en distintos sitios.

Aunque esto puede ser correcto desde el punto de vista normativo, dificulta verificar el sistema globalmente.

### Acción

Mantener las reglas normativas en su lugar actual, pero crear una tabla de auditoría:

```text
Invariant
Owner
Enforced by
Test
Failure mode
```

No sería otra fuente normativa; sería un índice de verificación.

### Prioridad

**Alta.**

---

# 8. Contexto y conocimiento

## AUD-009 — `KNOWLEDGE_CONTEXT` y memoria están bien conceptualizados

La memoria post-merge usa:

```text
hechos deterministas
+
Curator
+
staging
+
anclas
+
validación
```

y evita que el razonamiento interno del Worker se convierta en memoria persistente.

### Estado

**Buena decisión.**

La especificación también exige medir si la memoria realmente aporta utilidad neta.

---

## AUD-010 — Falta convertir el concepto de "utilidad de memoria" en una prueba operativa temprana

La especificación contempla:

```text
Memory net utility
```

pero es una métrica longitudinal.

### Riesgo

Puede invertirse bastante esfuerzo en una memoria que todavía no demuestra valor.

### Acción

Crear un benchmark inicial con:

```text
sin memory
vs
memory
```

sobre las mismas tareas y medir:

```text
success
retries
tokens
latency
```

### Prioridad

**Media-Alta.**

---

# 9. Failure handling

## AUD-011 — Buena separación entre clasificación y estrategia

`Failure Classifier` no decide libremente una reparación; utiliza un enum cerrado y el controlador gobierna los reintentos.

### Estado

**Sólido conceptualmente.**

---

## AUD-012 — Falta una implementación operativa verificable del Failure Classifier

La especificación define:

```text
SYNTAX_ERROR
TEST_FAILURE
CONTEXT_MISSING
FLAKY_TEST
ENVIRONMENT_ERROR
DEPENDENCY_ERROR
POLICY_VIOLATION
MERGE_CONFLICT
REVIEW_REJECTED
BUDGET_EXHAUSTED
UNKNOWN
```

y el registro indica un modelo de dominio para `FailureCode`, pero esto no demuestra todavía un clasificador E2E que convierta resultados reales de ejecución en esas clases.

### Acción

Construir fixtures de fallo:

```text
syntax
test
environment
dependency
policy
merge
review
budget
```

y verificar:

```text
observed failure
→ expected FailureCode
→ expected FSM action
```

### Prioridad

**Alta.**

---

# 10. Verification Guard

## AUD-013 — El modelo de verificación independiente es uno de los puntos más fuertes

La arquitectura protege:

```text
protected_paths
harness
baseline
candidate
manifest
```

y separa:

```text
Worker
Test Author
Verification Guard
Independent Reviewer
```

### Estado

**Fuerte a nivel de diseño.**

---

## AUD-014 — La afirmación de independencia requiere validación E2E

La independencia está muy bien definida en papel, pero necesita verificarse en escenarios adversariales.

Ejemplo de test de seguridad:

```text
Worker
→ intenta modificar test protegido
→ PatchSet
→ Policy Validation
→ Verification Guard
```

y otro:

```text
Worker
→ hace que los tests aparentemente pasen alterando el arnés
→ Protector restaura
→ test debería seguir detectando el problema
```

### Prioridad

**Alta.**

---

# 11. Sandbox y aislamiento

## AUD-015 — La separación de zonas de red está bien razonada

La arquitectura distingue:

```text
Z1 Control Plane
Z2 Model Gateway
Z3 Research
Z4 Code Sandbox
Z5 Host
```

y establece que `network none` corresponde al sandbox, no al sistema entero.

### Estado

**Correcto y conceptualmente importante.**

---

## AUD-016 — La matriz de aislamiento necesita prueba en runtime real

La especificación diferencia:

```text
LOW/MEDIUM
HIGH
CRITICAL
```

con:

```text
rootless
gVisor/Kata
microVM
```

### Riesgo

Es posible que el desarrollo local soporte solo uno de esos perfiles.

### Acción

Definir un capability de plataforma:

```text
sandbox_profile_available
```

y rechazar el job si el perfil requerido no existe.

La especificación ya indica esta intención para límites de recursos; debe comprobarse del mismo modo para el aislamiento.

### Prioridad

**Alta.**

---

# 12. Datos y secretos

## AUD-017 — La política de datos está correctamente separada del riesgo

La especificación distingue:

```text
public
internal
confidential
secret
```

y no permite que el LLM sea quien decida la clasificación.

### Estado

**Buena decisión.**

---

## AUD-018 — El camino de redacción debe probarse con fixtures de secretos

La clasificación es una frontera de seguridad, por lo que no basta con tests unitarios del enum.

### Acción

Crear repositorios sintéticos que contengan:

```text
API keys
private keys
.env
tokens
credential-like strings
```

y comprobar:

```text
no secret
→ prompt
→ logs
→ events
→ reports
→ model request
```

### Prioridad

**Alta.**

---

# 13. Model Gateway

## AUD-019 — El registry está bien planteado

La clave:

```text
(provider, platform, model_id)
```

y el almacenamiento de:

```text
capabilities
lifecycle
pricing
verified_at
data_policy
region
```

es una base razonable.

### Estado

**Correcto.**

---

## AUD-020 — Falta validar la selección de modelos completa

La especificación define:

```text
role
→ capabilities
→ data policy
→ availability
→ latency
→ expected cost
```

pero el registro de implementación no demuestra aún que el selector operativo recorra toda esta cadena.

### Acción

Tests parametrizados:

```text
model valid
model wrong capability
model retired
model wrong region
model wrong data policy
model unavailable
model circuit breaker open
```

### Prioridad

**Alta.**

---

# 14. Economía y recursos

## AUD-021 — El modelo económico está mejor definido que en la mayoría de arquitecturas agénticas

La especificación distingue:

```text
concurrency
RPM
TPM
quota
budget reservation
actual reconciliation
circuit breaker
expected cost
```

### Estado

**Buena especificación.**

---

## AUD-022 — Las garantías económicas todavía son más contractuales que operativas

La reserva atómica requiere SQLite/WAL o equivalente, pero no se demuestra en el registro de implementación que el flujo:

```text
reserve
→ call
→ reconcile
→ release
```

esté integrado con el Gateway real.

### Acción

Test de concurrencia:

```text
N jobs
+
budget limit
+
parallel model calls
```

y demostrar:

```text
no overspend
no double reservation
no lost reconciliation
```

### Prioridad

**Alta para P1.**

---

# 15. Git, worktrees y merge

## AUD-023 — La arquitectura de worktree es adecuada

El registro indica la implementación de:

```text
manager.py
patch_applier.py
merge_controller.py
```

y un lock de merge por repositorio.

### Estado

**Buena base.**

---

## AUD-024 — Falta una prueba de concurrencia real de merges

La especificación exige serialización por repositorio.

### Acción

Crear un escenario:

```text
job A
job B
job C
```

con worktrees distintos y commits simultáneos.

Debe demostrarse:

```text
merge serialized
no corruption
no lost commit
no race on lock
```

### Prioridad

**Alta.**

---

# 16. Obsolescencia del plan

## AUD-025 — La regla `STALE_PLAN` está bien especificada

La combinación:

```text
current_commit
scope
dependency_closure
protected_paths
```

está correctamente diferenciada entre:

```text
replan
```

y:

```text
automatic rebase
```

### Estado

**Sólido.**

---

## AUD-026 — Falta una prueba que cubra el límite exacto de la dependencia

Especialmente:

```text
changed file outside scope
changed dependency outside direct scope
changed protected path
changed config with indirect impact
```

### Acción

Construir una matriz de casos frontera.

### Prioridad

**Media-Alta.**

---

# 17. Skills

## AUD-027 — El sistema de skills tiene un modelo de permisos correcto

La regla:

```text
skill permissions
    =
requested permissions
    ∩
approved scope
    ∩
project policy
```

es consistente con least privilege.

Además:

```text
skill can increase risk
skill cannot reduce risk
```

### Estado

**Correcto conceptualmente.**

---

## AUD-028 — El runtime de skills todavía forma parte del gap P1

No aparece como parte de los componentes P0 implementados.

### Prioridad

**Media.**

No debería adelantarse al E2E central.

---

# 18. Research

## AUD-029 — La separación Research Plane / Code Sandbox está bien definida

Especialmente:

```text
web = untrusted
code = sandboxed
```

y el LLM extractor no recibe herramientas.

### Estado

**Buena separación.**

---

## AUD-030 — Research no debe convertirse en dependencia del MVP

La capacidad de research añade:

```text
proxy
allowlist
browser
fetcher
evidence validation
```

y aumenta considerablemente el área de superficie.

### Acción

Mantenerla independiente del camino mínimo:

```text
core coding E2E
```

### Prioridad

**Media.**

---

# 19. Observabilidad y auditoría

## AUD-031 — Event sourcing es una buena elección

La arquitectura define:

```text
events.jsonl
+
prev_hash
+
event_hash
```

y `manifest.json` como proyección regenerable.

### Estado

**Muy buena decisión.**

---

## AUD-032 — Falta demostrar recuperación tras corrupción

La especificación declara detección de manipulación del log.

### Acción

Test explícito:

```text
event N alterado
→ hash chain invalid
→ job no puede ser considerado íntegro
```

y:

```text
manifest eliminado
→ regenerate from events
```

### Prioridad

**Alta.**

---

# 20. Benchmark y evidencia experimental

## AUD-033 — La decisión de medir antes de optimizar es correcta

La especificación evita afirmar ahorros sin datos y define benchmark, baseline y no inferioridad.

### Estado

**Muy sólido conceptualmente.**

---

## AUD-034 — El benchmark actual es insuficiente para demostrar el sistema completo

El benchmark mostrado en el registro cubre:

```text
intent match
false-direct
risk monotonicity
final state
duration
chain integrity
```

pero esto todavía no demuestra:

```text
real task success
token savings
cost per successful task
regression rate
human review time
context efficiency
E2E provider reliability
```

### Conclusión

El benchmark actual debe considerarse:

```text
foundation / invariant benchmark
```

no todavía:

```text
system performance benchmark
```

### Prioridad

**Alta.**

---

# 21. CLI

## AUD-035 — La CLI ya dispone de un buen esqueleto

El registro indica:

```text
myagentos route
myagentos benchmark
myagentos status
myagentos verify
```

### Estado

**Adecuado para el estado actual.**

---

## AUD-036 — Falta una interfaz E2E que represente el producto real

La herramienta todavía necesita poder expresar una operación equivalente a:

```text
task
→ plan
→ approve
→ execute
→ verify
→ review
→ merge
```

para validar el flujo completo desde el punto de vista del usuario.

### Prioridad

**Alta.**

---

# 22. Madurez actual estimada por área

Esta tabla es una clasificación de estado de ingeniería, no una puntuación de calidad.

| Área | Estado documental | Estado indicado por implementación | Próxima validación |
|---|---|---|---|
| Modelos de dominio | Definido | Implementado | tests de propiedades |
| Event Store | Definido | Implementado | recuperación/corrupción |
| FSM | Definido | Implementado | E2E + edge cases |
| Policy Engine | Definido | Implementado | tests de invariantes |
| Router v0 | Definido | Implementado | benchmark más amplio |
| Worktree | Definido | Implementado | concurrencia |
| Sandbox | Definido | Implementado | runtime por perfiles |
| Verification Guard | Definido | Implementado | escenarios adversariales |
| Model Gateway | Definido | Parcial/Estructural | E2E real |
| Worker | Definido | Pendiente según registro | tool loop |
| Context Compiler | Definido | Pendiente según registro | dependency closure |
| Failure Classifier | Definido | modelo creado / integración pendiente | fallos reales |
| Budget Governor | Definido | no demostrado E2E | concurrencia/coste |
| Skills | Definido | P1 | runtime |
| Research | Definido | P1 | pipeline |
| Independent Review LLM | Definido | P1 | review E2E |
| Knowledge Update | Definido | P1 | staging/promoción |
| Benchmark de sistema | Definido | foundation | tareas reales |

---

# 23. Áreas donde conviene reducir ambigüedad

## AUD-037 — Estado del job vs estado del sistema

Existe una diferencia entre:

```text
job completed
```

y:

```text
system operational
```

Un `COMPLETE` solo significa que un job concreto cumplió sus condiciones.

No implica:

```text
provider healthy
sandbox universally supported
memory useful
benchmark sufficient
```

### Acción

Mantener explícitamente:

```text
job status
system readiness
```

como conceptos diferentes.

---

## AUD-038 — Risk Level vs Finding Severity

La arquitectura de la nueva característica que se desarrollará posteriormente no debe mezclarse con la semántica actual, pero la auditoría identifica que esta distinción ya es necesaria conceptualmente:

```text
RiskLevel
    = riesgo del cambio que Agentic OS pretende realizar

FailureCode
    = fallo de la ejecución de Agentic OS

Finding
    = problema detectado en el proyecto
```

### Acción

Mantener estas tres taxonomías completamente separadas cuando el sistema amplíe sus capacidades de diagnóstico.

---

# 24. Deuda de documentación

## AUD-039 — El documento original es suficientemente detallado para diseñar, pero ya necesita un mapa de implementación

Una vez que la implementación crece, una especificación de 1800+ líneas puede volverse difícil de utilizar como guía directa de desarrollo.

### Acción

Añadir en futuras versiones un índice operativo:

```text
component
→ section
→ source path
→ tests
→ current status
```

Ejemplo:

```yaml
component: Policy Engine
spec: §5 §12 §23
source:
  - src/myagentos/policy/engine.py
  - src/myagentos/policy/validator.py
tests:
  - tests/test_policy.py
status: implemented
verification: unit
```

Esto no debe reemplazar la especificación normativa.

---

## AUD-040 — El historial de cambios debería distinguir "document change" de "validated behavior"

El Appendix A registra cambios de arquitectura y estado de proveedores.

Sería útil separar:

```text
architecture changes
implementation changes
benchmark evidence
provider freshness
```

para evitar interpretar un cambio documental como evidencia de que el runtime ya lo implementa.

---

# 25. Prioridades técnicas derivadas de la auditoría

No se recomienda ampliar funcionalidades antes de cerrar el siguiente camino mínimo:

```text
1. Context Compiler mínimo real
        ↓
2. Worker + Tool Broker Loop
        ↓
3. E2E con modelo real
        ↓
4. real PatchSet
        ↓
5. Policy Validation
        ↓
6. Verification Guard
        ↓
7. Independent Review
        ↓
8. Merge Controller
        ↓
9. Audit Trail completo
```

Después:

```text
10. Failure Classifier operativo
11. Context Expansion
12. Budget/Rate limiting/Circuit breaker
13. Skills
14. Research
15. Memory/Knowledge
16. optimizaciones
```

La razón es que el sistema necesita demostrar primero que el **camino fundamental de desarrollo funciona**, antes de optimizarlo o multiplicar sus capacidades auxiliares.

---

# 26. Definición recomendada de "MVP real"

El sistema debería considerarse MVP funcional únicamente cuando pueda hacer lo siguiente en un repositorio de prueba real:

```text
crear job
   ↓
routing
   ↓
construir contexto
   ↓
generar plan
   ↓
evaluar riesgo
   ↓
obtener aprobación cuando corresponde
   ↓
crear worktree
   ↓
Worker real
   ↓
tool calls gobernadas
   ↓
PatchSet real
   ↓
Policy Validation
   ↓
sandbox
   ↓
Verification Guard
   ↓
Independent Review
   ↓
merge
   ↓
Audit Trail
```

Y todo ello debe dejar:

```text
evento
+
estado
+
hash
+
coste
+
modelo
+
evidencia
```

suficientes para reconstruir el job.

---

# 27. Pruebas que faltan para poder considerar robusta la base

## 27.1 Tests de seguridad

```text
path traversal
symlink escape
protected path mutation
secret leakage
unauthorized capability
network escape
tool invocation outside token
```

## 27.2 Tests de concurrencia

```text
two jobs same repo
simultaneous budget reservation
parallel model calls
merge lock contention
event append contention
```

## 27.3 Tests de consistencia

```text
risk monotonicity
approval invalidation
stale plan
patch hash mismatch
event hash corruption
manifest regeneration
```

## 27.4 Tests E2E

```text
simple code task
multi-file task
test failure
context expansion
environment failure
review rejection
merge conflict
budget exhaustion
```

---

# 28. Riesgos de ingeniería detectados

## AUD-041 — Sobreextensión temprana

La arquitectura ya incorpora:

```text
routing
research
memory
skills
provider lifecycle
economics
security
review
sandbox
```

antes de que el camino E2E central esté plenamente operativo.

### Riesgo

Distribuir esfuerzo en demasiadas superficies y retrasar la validación de la tesis principal.

### Acción

Priorizar:

```text
Context Compiler
+
Worker
+
E2E
```

antes de nuevas abstracciones.

---

## AUD-042 — Optimización antes de baseline completo

La arquitectura tiene prompt caching, routing local, modelos económicos y selección por coste.

Estas son decisiones correctas como diseño, pero su beneficio todavía depende de benchmark.

### Acción

No tratar:

```text
menos tokens
menos coste
más rapidez
```

como características probadas hasta medirlas.

La propia especificación ya establece esta regla; debe conservarse rigurosamente.

---

## AUD-043 — Complejidad accidental del contrato

Hay muchos contratos pequeños:

```text
plan
approval
risk
token
patch
failure
event
manifest
registry
skill
research
ADR
knowledge
```

Esto es útil para gobernanza, pero aumenta el coste de evolución.

### Acción

Antes de añadir contratos nuevos, comprobar:

```text
¿es realmente un objeto de dominio nuevo?
¿o es una vista/proyección de uno existente?
```

La arquitectura debe evitar crear entidades que dupliquen estado.

---

# 29. Aspectos que no requieren cambios estructurales inmediatos

La auditoría no detecta motivo para replantear:

```text
Job Controller como autoridad de FSM
Model Gateway como único egreso
Capability Tokens
Worktrees efímeros
Protected Verification
Event Store hash-chained
risk monotonicity
provider-agnostic registry
untrusted inheritance
```

Estos elementos forman una base suficientemente clara para continuar la implementación.

---

# 30. Resultado de la auditoría

## Diagnóstico

La v2.1 está en una posición de:

```text
arquitectura detallada
+
fundamentos P0 implementados según el registro
+
validación unitaria declarada
+
benchmark de invariantes inicial
```

pero todavía no en:

```text
sistema E2E validado sobre tareas reales
```

La principal brecha es operacional, no conceptual.

---

# 31. Condición de salida de la siguiente iteración

Antes de declarar una siguiente versión de arquitectura como consolidada, debería existir evidencia de:

```text
[ ] Worker real funcionando
[ ] Context Compiler real funcionando
[ ] E2E con proveedor real
[ ] PatchSet real aplicado
[ ] Policy Validation real
[ ] Verification Guard real
[ ] Review real
[ ] Merge real
[ ] Event Trail completo
[ ] Failure Classifier integrado
[ ] Costes registrados
[ ] benchmark E2E reproducible
```

Después de eso, sí tiene sentido medir:

```text
tokens
coste
latencia
reintentos
regresiones
human review time
memory utility
```

---

# 32. Conclusión

La arquitectura no necesita una reescritura conceptual en este punto.

La prioridad es **convertir las garantías escritas en comportamiento observable**.

El camino recomendado es:

```text
DOCUMENTO
   ↓
CONTRATO
   ↓
IMPLEMENTACIÓN
   ↓
TEST UNITARIO
   ↓
TEST DE PROPIEDAD
   ↓
TEST E2E
   ↓
BENCHMARK
```

y repetirlo para cada frontera importante.

El registro de implementación muestra que ya se ha construido una buena parte de las fundaciones deterministas. El siguiente salto de madurez consiste en conectar esas piezas y demostrar que un repositorio real puede atravesar el sistema completo de principio a fin.

La arquitectura debe continuar evitando dos extremos:

```text
LLM con demasiada autoridad
```

y:

```text
framework excesivamente complejo antes de probar el flujo central
```

La base actual permite evitar ambos, siempre que la siguiente etapa se concentre en el camino E2E y en transformar los contratos P1 en comportamiento medible.

---

# Apéndice A — Checklist compacto

## Arquitectura

```text
[✓] componentes claramente separados
[✓] autoridad determinista
[✓] risk monotonicity definida
[✓] capability model definido
[✓] sandbox definido
[✓] verification boundary definida
[✓] provider registry definido
[✓] audit trail definido
```

## Implementación indicada

```text
[✓] dominio
[✓] Event Store
[✓] FSM
[✓] Policy
[✓] Router v0
[✓] Worktree
[✓] Sandbox
[✓] Verification Guard
[✓] Gateway
[✓] Benchmark foundation
[✓] CLI foundation

[ ] Worker loop
[ ] Context Compiler real
[ ] E2E completo
[ ] Failure Classifier operativo
[ ] Economic controls E2E
[ ] Independent Review LLM
[ ] Skills runtime
[ ] Research pipeline
[ ] Knowledge runtime completo
```

## Verificación

```text
[ ] property tests
[ ] adversarial security tests
[ ] concurrency tests
[ ] provider failure tests
[ ] real repository E2E
[ ] performance benchmark
[ ] cost benchmark
```

---

# Apéndice B — Principio rector de esta auditoría

La unidad de progreso no debe ser:

```text
"se ha creado otro módulo"
```

sino:

```text
"una propiedad del sistema que antes estaba especificada
ahora está implementada, verificada y medida."
```

Ese cambio de criterio permite que la siguiente fase del proyecto avance desde una arquitectura muy detallada hacia un sistema comprobablemente funcional.
