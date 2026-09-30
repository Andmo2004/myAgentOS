# Manual de Usuario — MYA (myAgentOS)

> **Tú hablas con Mya. Los agentes hacen el trabajo. myAgentOS gobierna y garantiza la seguridad.**

Este manual explica cómo instalar, configurar y usar MYA en el día a día, desde la primera ejecución hasta los comandos especializados. Está escrito para desarrolladores que quieren aprovechar el sistema al máximo sin necesidad de conocer la arquitectura interna.

---

## Tabla de Contenidos

1. [Instalación](#1-instalación)
2. [Primera Vez: Configuración de un Modelo de IA](#2-primera-vez-configuración-de-un-modelo-de-ia)
3. [Iniciar Mya (Interfaz TUI)](#3-iniciar-mya-interfaz-tui)
4. [Cómo Hablar con Mya](#4-cómo-hablar-con-mya)
5. [Referencia de Comandos Slash](#5-referencia-de-comandos-slash)
   - [5.1 Configuración y Modelos](#51-configuración-y-modelos)
   - [5.2 Observabilidad](#52-observabilidad)
   - [5.3 Modos de Trabajo y Análisis](#53-modos-de-trabajo-y-análisis)
   - [5.4 Decisión y Expertise Especializado](#54-decisión-y-expertise-especializado)
   - [5.5 Proyectos](#55-proyectos)
   - [5.6 Presentación Visual](#56-presentación-visual)
   - [5.7 Utilidades de Sesión](#57-utilidades-de-sesión)
6. [Atajos de Teclado](#6-atajos-de-teclado)
7. [CLI Avanzada (`myagentos`)](#7-cli-avanzada-myagentos)
8. [Gestión de Proyectos](#8-gestión-de-proyectos)
9. [Preguntas Frecuentes](#9-preguntas-frecuentes)

---

## 1. Instalación

### Requisitos

- **Python** ≥ 3.12
- **Git** ≥ 2.30
- **uv** (recomendado) o `pip`

### Instalación con `uv` (recomendado)

```bash
# 1. Clonar el repositorio
git clone https://github.com/Andmo2004/myAgentOS.git
cd myAgentOS

# 2. Crear entorno virtual y sincronizar dependencias
uv venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate
uv sync
```

### Instalación con `pip`

```bash
git clone https://github.com/Andmo2004/myAgentOS.git
cd myAgentOS
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Verificar la instalación

```bash
uv run mya --version  # o: mya --version si el entorno está activo
```

---

## 2. Primera Vez: Configuración de un Modelo de IA

Mya puede operar en **modo simulador local** (sin coste, sin red) o conectada a un modelo real. Tienes tres opciones de proveedor:

| Proveedor | Variable de Entorno | Modelo por Defecto |
|---|---|---|
| **Anthropic (Claude)** | `ANTHROPIC_API_KEY` | `claude-3-5-sonnet-latest` |
| **OpenAI** | `OPENAI_API_KEY` | `gpt-4o` |
| **Google Gemini** | `GEMINI_API_KEY` | `gemini-2.0-flash` |
| **Simulador local** | *(ninguna)* | `mock-mya` (sin LLM) |

### Opción A: Configurar desde la propia interfaz de Mya (recomendado)

Una vez que inicies Mya, usa el comando `/key`:

```text
/key claude  sk-ant-api03-...
/key openai  sk-proj-...
/key gemini  AIzaSy...
```

Mya guardará la clave en el archivo `.env` del proyecto de forma segura y activará el modelo automáticamente.

### Opción B: Configurar mediante el archivo `.env`

Copia el archivo de ejemplo y edítalo:

```bash
cp .env.example .env
```

Luego abre `.env` y descomenta la clave que quieras usar:

```dotenv
# Anthropic Claude (prioridad más alta en detección automática)
ANTHROPIC_API_KEY=sk-ant-api03-...

# OpenAI
# OPENAI_API_KEY=sk-proj-...

# Google Gemini
# GEMINI_API_KEY=AIzaSy...

# Forzar un modelo concreto (opcional)
# MYA_MODEL=claude-3-5-haiku-latest
```

> [!NOTE]
> El archivo `.env` está en `.gitignore` y **nunca se sube al repositorio**. Tus claves permanecen locales.

### Prioridad de detección automática

Si tienes varias claves configuradas, Mya elige el modelo en este orden:

1. `MYA_MODEL` (si está definida, siempre tiene prioridad)
2. `ANTHROPIC_API_KEY` → `claude-3-5-sonnet-latest`
3. `OPENAI_API_KEY` → `gpt-4o`
4. `GEMINI_API_KEY` → `gemini-2.0-flash`
5. Sin claves → `mock-mya` (simulador local)

---

## 3. Iniciar Mya (Interfaz TUI)

```bash
# Forma rápida (con entorno activado)
mya

# Con uv (sin activar el entorno)
uv run mya
```

Verás la pantalla de bienvenida con información de tu repositorio y el modelo activo:

```text
                 MYA · Agentic OS

  Repository   myAgentOS
  Branch       main
  Commit       a2ce89e
  Status       clean
  Model        claude-3-5-sonnet-latest

  Ready. Describe what you want to build or fix.

  /help  commands    /key  api keys    /model  models    /projects  projects
```

El campo de entrada en la parte inferior está listo para escribir. Escribe tu petición en lenguaje natural o usa un comando slash y pulsa **Enter**.

---

## 4. Cómo Hablar con Mya

### Lenguaje Natural (recomendado para tareas)

No necesitas recordar ninguna sintaxis especial. Simplemente describe lo que quieres:

```text
añade validación de email al formulario de registro
```
```text
arregla los tests que fallan en src/auth/
```
```text
explícame qué hace este código
```
```text
muéstrame el estado de mis proyectos
```

Mya interpreta tu petición, la convierte en una intención estructurada y coordina los agentes necesarios. Si la tarea es ambigua o implica riesgo, Mya te hará preguntas antes de proceder.

### ¿Qué hace Mya y qué no hace?

| Mya **sí** hace | Mya **no** hace |
|---|---|
| Interpreta tus peticiones en lenguaje natural | Ejecutar comandos de sistema directamente |
| Formula preguntas de aclaración | Conceder permisos o capabilities |
| Explica el estado del sistema | Aprobar planes o diffs por sí sola |
| Comenta la ejecución con su personalidad | Modificar la FSM de estados |
| Propone el siguiente paso | Bajar el nivel de riesgo de una tarea |

> [!IMPORTANT]
> **Principio de Gobernanza:** Mya interpreta y propone. El núcleo determinista (Job Controller, Policy Engine) decide y autoriza. Los Workers ejecutan. La Verification Guard verifica.

---

## 5. Referencia de Comandos Slash

Todos los comandos empiezan con `/` y se escriben directamente en el campo de entrada de Mya.

---

### 5.1 Configuración y Modelos

#### `/keys` — Ver estado de las claves API

Muestra un resumen enmascarado de tus claves configuradas y el modelo activo:

```text
/keys
```

**Salida de ejemplo:**
```text
  • Claude  (ANTHROPIC_API_KEY): sk-ant...5f2a
  • OpenAI  (OPENAI_API_KEY):    No configurada
  • Gemini  (GEMINI_API_KEY):    No configurada
  • Modelo activo:               claude-3-5-sonnet-latest
  • Archivo de claves:           .env
```

#### `/key <proveedor> <api_key>` — Configurar una clave API

Registra una clave API en vivo y la persiste en el archivo `.env`. El modelo se activa automáticamente.

```text
/key claude  sk-ant-api03-xxxxxxxxxxxxxxxx
/key openai  sk-proj-xxxxxxxxxxxxxxxx
/key gemini  AIzaSyxxxxxxxxxxxxxxxx
```

#### `/model` — Ver modelos disponibles

Sin argumento, muestra el modelo activo y los adaptadores registrados:

```text
/model
```

#### `/model <nombre>` — Cambiar el modelo activo

```text
/model claude-3-5-sonnet-latest
/model claude-3-5-haiku-latest
/model claude-3-opus-latest
/model gpt-4o
/model gpt-4o-mini
/model gemini-2.0-flash
/model gemini-1.5-pro
```

> [!TIP]
> Si usas `/model` con un modelo Claude y no tienes `ANTHROPIC_API_KEY` configurada, Mya te avisará con instrucciones para configurarla primero.

#### `/settings` — Sinónimo de `/key`

Alias alternativo para gestión de claves.

---

### 5.2 Observabilidad

Estos comandos proyectan el estado real del sistema **sin consumir tokens de LLM**. Son inmediatos y gratuitos.

#### `/info` — Estado de la sesión y presupuesto de tokens 🟢

```text
/info
```

Muestra: sesión activa, repositorio, tokens consumidos en la sesión, presupuesto restante y coste estimado.

#### `/telemetry` — Actividad de agentes y consumo detallado 🟢

```text
/telemetry
```

Muestra: desglose de tokens por agente, latencia de llamadas LLM, historial de jobs de la sesión y coste acumulado.

#### `/monitor` — Monitor en vivo de agentes y archivos 🟢

```text
/monitor
```

Proyecta en tiempo real: jobs activos en la FSM, archivos siendo leídos o modificados, estado de verificación y aprobaciones pendientes.

#### `/status` — Estado de Git y proyecto

```text
/status
```

Muestra: rama activa, commit HEAD, archivos modificados (working tree) y perfil tecnológico del repositorio.

---

### 5.3 Modos de Trabajo y Análisis

#### `/fast <prompt>` — Ruta rápida 🟢

Para tareas mecánicas seguras con mínima sobrecarga conversacional:

```text
/fast arregla el typo en src/utils.py
/fast añade el import que falta en cli.py
```

> [!NOTE]
> Si el router detecta términos sensibles (autenticación, migraciones de base de datos, secretos), `/fast` escala automáticamente a ruta planificada con supervisión completa.

#### `/sci_mode <prompt>` — Modo científico estructurado 🟡

Para análisis riguroso con metodología formal:

```text
/sci_mode compara las estrategias de caché: Redis vs Memcached vs in-process
/sci_mode evalúa el impacto de añadir índices a la tabla users
```

Genera una respuesta estructurada en formato: **Pregunta → Hipótesis → Metodología → Evidencia → Conclusiones**.

#### `/deep_research <query>` — Investigación exhaustiva 🔴

Para investigación en documentación, estándares y mejores prácticas. **No modifica código por defecto.**

```text
/deep_research arquitectura event sourcing vs CRUD para sistemas financieros
/deep_research mejores prácticas OAuth2 con PKCE en aplicaciones móviles
```

#### `/optimize <target>` — Análisis de rendimiento 🟡

Analiza cuellos de botella y candidatos de optimización sin hacer cambios automáticos:

```text
/optimize src/database/queries.py
/optimize el endpoint POST /api/users que tarda más de 2 segundos
```

---

### 5.4 Decisión y Expertise Especializado

#### `/decision <pregunta>` — Perspectivas independientes 🟠

Reúne **5 perspectivas independientes** (Arquitecto, Rendimiento, Seguridad, Mantenibilidad y Coste) para decisiones de diseño difíciles:

```text
/decision ¿usar SQLite o PostgreSQL para el registro de auditoría local?
/decision ¿implementar autenticación con JWT o sesiones de servidor?
/decision ¿migrar a microservicios o mantener el monolito?
```

#### `/cloud <prompt>` — Arquitectura cloud e IAM 🟡

Análisis especializado de infraestructura cloud, permisos IAM y arquitecturas distribuidas:

```text
/cloud diseño de VPC con subredes públicas y privadas en AWS
/cloud revisar los permisos IAM del rol de ejecución Lambda
```

#### `/security <prompt>` — Auditoría de ciberseguridad 🟡

Auditoría especializada contra vulnerabilidades comunes (OWASP, CWE) y controles de seguridad:

```text
/security analiza los endpoints de autenticación en src/auth/
/security revisa el manejo de inputs en el formulario de búsqueda
```

> [!WARNING]
> El modo `/security` sólo puede **elevar** el nivel de riesgo de una tarea, nunca reducirlo. Es por diseño: una auditoría que encuentra problemas serios requiere más supervisión, no menos.

---

### 5.5 Proyectos

#### `/projects` — Explorador de proyectos (Ctrl+P)

Abre la pantalla interactiva del explorador de proyectos:

```text
/projects
```

Equivalente a pulsar **Ctrl+P**. Muestra todos los proyectos registrados con sus estados, tags y acciones rápidas.

#### `/categorize` — Categorizar el repositorio actual

```text
/categorize
```

Escanea el repositorio y genera o actualiza el perfil tecnológico (lenguajes, frameworks, tipos de app, controles de calidad).

---

### 5.6 Presentación Visual

#### `/theme [nombre]` — Cambiar el tema visual

```text
/theme              # Ver tema activo y opciones disponibles
/theme default      # Tema estándar con colores completos
/theme minimal      # Interfaz limpia con colores reducidos
/theme high_contrast# Alto contraste para accesibilidad
/theme monochrome   # Sin color, solo texto
```

#### `/motion [modo]` — Control de animaciones

```text
/motion             # Ver modo actual
/motion full        # Todas las microanimaciones activas
/motion reduced     # Animaciones reducidas (recomendado)
/motion off         # Sin animaciones (máxima accesibilidad)
```

#### `/avatar [modo]` — Estilo del avatar de Mya

```text
/avatar             # Ver modo actual y preview
/avatar dot         # ● Mya  (modo por defecto, mínimo)
/avatar glyph       # ╭─ Mya ──╮  (bordes decorativos)
/avatar ascii       # Avatar compuesto con expresiones reactivas
/avatar minimal     # [Mya]  (puro texto)
```

#### `/compact` / `/dense` — Densidad visual

```text
/compact   # Reduce el espaciado entre mensajes
/dense     # Aumenta el espaciado (más legible)
```

---

### 5.7 Utilidades de Sesión

#### `/help` — Mostrar ayuda rápida

```text
/help
```

#### `/clear` — Limpiar la conversación

```text
/clear
```

Limpia todos los mensajes del panel de conversación. No afecta al historial de jobs ni al EventStore.

#### `/status` — Estado del proyecto

```text
/status
```

#### `/exit` / `/quit` — Salir de Mya

```text
/exit
/quit
```

---

## 6. Atajos de Teclado

| Atajo | Acción |
|---|---|
| **Enter** | Enviar mensaje o comando |
| **↑ / ↓** | Navegar por el historial de comandos |
| **Ctrl+P** | Abrir explorador de proyectos |
| **Ctrl+C** | Cancelar acción en curso |
| **Ctrl+D** | Salir de Mya |
| **Escape** | Escapar / cancelar entrada |
| **Tab** | Navegar entre elementos de la UI |

---

## 7. CLI Avanzada (`myagentos`)

Además de la interfaz TUI, myAgentOS expone una CLI completa para integraciones, CI/CD y automatización.

### Ejecutar una tarea autónoma

```bash
uv run myagentos run "Añade validación de email en src/auth/validators.py"

# Con auto-aprobación (útil en CI/CD)
uv run myagentos run "Corrige imports en src/utils.py" --auto-approve

# Especificando el repositorio y el modelo
uv run myagentos run "Añade tests unitarios" --repo ../otro-repo --model mock
```

### Inspeccionar el enrutador local (sin tokens)

```bash
uv run myagentos route "añade autenticación OAuth"
uv run myagentos route "/direct fix typo in README"
```

Muestra la intención clasificada, la regla aplicada y el nivel de riesgo **sin hacer ninguna llamada a LLM**.

### Estado de un job y verificación criptográfica

```bash
# Estado actual en la FSM
uv run myagentos status job-d327c605

# Verificar integridad de la cadena SHA-256
uv run myagentos verify job-d327c605
```

### Benchmark comparativo

```bash
# Suite rápida
uv run myagentos benchmark --suite smoke

# Suite de seguridad y adversariales
uv run myagentos benchmark --suite security

# Suite completa con reporte JSON
uv run myagentos benchmark --suite full --output reporte.json
```

### Auditoría de continuidad (PCA)

```bash
uv run myagentos continue run --dynamic
uv run myagentos continue report
```

---

## 8. Gestión de Proyectos

myAgentOS mantiene un registro centralizado de proyectos en `~/.myagentos/projects.json`.

```bash
# Listar proyectos activos
uv run myagentos project list

# Registrar un proyecto existente en disco
uv run myagentos project add /ruta/a/mi-proyecto --name "Nombre del Proyecto"

# Clonar un repositorio remoto
uv run myagentos project clone https://github.com/usuario/repo.git

# Ver los tags de categorización de un proyecto
uv run myagentos project tags <project_id>

# Papelera
uv run myagentos project trash move <project_id>     # Mover a papelera
uv run myagentos project trash list                   # Ver papelera
uv run myagentos project trash restore <project_id>   # Restaurar
uv run myagentos project trash purge <project_id> --confirm  # Eliminar permanentemente
```

### Categorización de repositorios

```bash
# Escanear y generar perfil tecnológico
uv run myagentos categorize

# Forzar re-escaneo ignorando caché
uv run myagentos categorize --force

# Exportar perfil en JSON
uv run myagentos categorize --json
```

El perfil generado incluye: lenguajes, frameworks, tipo de aplicación, controles de calidad (testing, linting, CI/CD) y etiquetas de stack.

---

## 9. Preguntas Frecuentes

### ¿Mya tiene acceso a Internet?

No. La red está deshabilitada por defecto en el sandbox donde los agentes ejecutan código. Solo el **Model Gateway** (Zona Z2) tiene acceso controlado a las APIs de los proveedores de LLM para inferencia. Nunca se envían tus archivos a terceros sin tu conocimiento.

### ¿Mis claves API se suben a algún servidor?

No. Las claves se almacenan únicamente en el archivo `.env` de tu directorio local, que está en `.gitignore`. Nunca se incluyen en commits ni se envían a ningún servidor externo.

### ¿Puedo usar Mya sin una clave API?

Sí. En modo `mock-mya` (sin ninguna clave configurada), Mya funciona como simulador local: procesa la interfaz, gestiona proyectos, muestra observabilidad y ejecuta el pipeline completo, pero las respuestas del modelo son simuladas. Es útil para pruebas y para explorar la interfaz sin coste.

### ¿Qué pasa cuando Mya pide aprobación?

Para tareas con nivel de riesgo `MEDIUM` o superior, el sistema te mostrará el plan antes de ejecutar y pedirá tu confirmación. Puedes revisar qué archivos se van a modificar, qué comandos se ejecutarán y cuál es el riesgo estimado. **Ningún cambio se aplica sin tu aprobación explícita** para esos niveles de riesgo.

### ¿Cómo añado Mya a mi repositorio de trabajo habitual?

Simplemente ejecuta `mya` desde el directorio de tu proyecto. Mya detecta automáticamente el repositorio Git y carga el perfil de proyecto si existe. Puedes también registrar el proyecto:

```bash
cd /ruta/a/mi-proyecto
uv run myagentos project add . --name "Mi Proyecto"
mya
```

### ¿Cómo cambio de Claude a GPT-4o en medio de una sesión?

Usa el comando `/model` directamente en la interfaz:

```text
/model gpt-4o
```

Si no tienes la clave de OpenAI configurada aún:

```text
/key openai sk-proj-...
```

### ¿Dónde se guarda el historial de jobs y el audit trail?

En `.myagentos/jobs/{job_id}/events.jsonl` dentro de tu repositorio. Cada evento incluye un hash SHA-256 encadenado para garantizar la integridad. Puedes verificar la cadena en cualquier momento:

```bash
uv run myagentos verify <job_id>
```

### ¿Puedo ver los cambios que va a hacer antes de aprobarlos?

Sí. Para jobs con riesgo `MEDIUM` o superior, el revisor independiente genera un diff completo que verás antes de que se aplique. Para jobs `LOW`, la aprobación es automática pero el audit trail siempre queda registrado.

---

## Documentación Adicional

| Documento | Descripción |
|---|---|
| [`docs/cli-reference.md`](cli-reference.md) | Referencia completa de la CLI con todas las opciones |
| [`docs/architecture.md`](architecture.md) | Arquitectura, zonas de seguridad y modelo de amenazas |
| [`docs/specification.md`](specification.md) | Especificación técnica maestra (v2.1) |
| [`docs/benchmark-guide.md`](benchmark-guide.md) | Guía del arnés de benchmark empírico |
| [`docs/continuity-specification.md`](continuity-specification.md) | Auditoría de continuidad de proyectos (PCA) |

---

*Manual de Usuario — MYA (myAgentOS) v2.2+*
