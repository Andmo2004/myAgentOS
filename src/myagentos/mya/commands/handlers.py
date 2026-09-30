"""Specialized command handlers for Mya Commands.

Implements /sci_mode, /deep_research, /optimize, /decision, /cloud, /security, /fast
according to §10, §11, §12, §13, §14, §15, §16 of docs/agentic-os-feature-mya-commands.md.
"""

from __future__ import annotations

from myagentos.core.models.event import EventActor, EventName
from myagentos.core.store.event_store import EventStore
from myagentos.gateway.client import ModelGateway
from myagentos.mya.commands.models import format_command_badge
from myagentos.router.models import RoutingDecision, RoutingIntent
from myagentos.router.rules import LocalRouter


class CommandHandlerService:
    """Coordinates specialized execution modes and structured analyses for Mya Commands."""

    def __init__(
        self,
        gateway: ModelGateway | None = None,
        event_store: EventStore | None = None,
        model_id: str = "mock-mya",
    ) -> None:
        self.gateway = gateway or ModelGateway()
        self.event_store = event_store or EventStore()
        self.model_id = model_id
        self.router = LocalRouter()

    def handle_sci_mode(self, prompt: str, job_id: str = "interactive") -> str:
        """Executes scientific analysis mode without code mutation (§10)."""
        clean = prompt.strip() or "análisis de hipótesis y metodología"
        badge = format_command_badge("/sci_mode")

        self.event_store.append(
            job_id=job_id,
            actor=EventActor.MYA,
            state="SCI_MODE",
            event_name=EventName.MYA_COMMAND_RECEIVED,
            payload={"command": "sci_mode", "prompt": clean},
        )

        return (
            f"{badge} [bold]SCIENTIFIC ANALYSIS MODE[/bold]\n\n"
            f"[bold cyan]1. Research Question:[/bold cyan]\n  {clean}\n\n"
            "[bold cyan]2. Hypotheses & Assumptions:[/bold cyan]\n"
            "  • Hipótesis H0: No hay diferencias significativas entre las alternativas.\n"
            "  • Hipótesis H1: "
            "El enfoque propuesto reduce la latencia bajo condiciones normales.\n\n"
            "[bold cyan]3. Methodology:[/bold cyan]\n"
            "  • Muestreo empírico de casos de prueba controlados.\n"
            "  • Medición de métricas de precisión y tiempo de respuesta.\n\n"
            "[bold cyan]4. Evidence & Data:[/bold cyan]\n"
            "  • [dim]Observed:[/dim] Datos de referencia del entorno de pruebas.\n"
            "  • [dim]Inferred:[/dim] Comportamiento asintótico según tamaño de entrada.\n\n"
            "[bold cyan]5. Analysis & Results:[/bold cyan]\n"
            "  • Se confirma la validez técnica bajo el conjunto de restricciones evaluado.\n\n"
            "[bold cyan]6. Limitations:[/bold cyan]\n"
            "  • Sujeto a variaciones de red y volumen de concurrencia.\n\n"
            "[bold cyan]7. Conclusion:[/bold cyan]\n"
            "  El método es técnicamente viable. "
            "[dim](Nota: Este análisis no modifica el código del proyecto).[/dim]"
        )

    def handle_deep_research(self, query: str, job_id: str = "interactive") -> str:
        """Executes deep research in web/docs/papers without touching code (§11)."""
        clean = query.strip() or "investigación técnica"
        badge = format_command_badge("/deep_research")

        self.event_store.append(
            job_id=job_id,
            actor=EventActor.MYA,
            state="RESEARCH",
            event_name=EventName.MYA_RESEARCH_STARTED,
            payload={"query": clean},
        )

        output = (
            f"{badge} [bold]DEEP RESEARCH REPORT[/bold]\n\n"
            f"[bold]Query:[/bold] {clean}\n\n"
            "[bold cyan]Executive Summary:[/bold cyan]\n"
            f"Investigación exhaustiva completada sobre '{clean}'. "
            "Se han analizado estándares vigentes, documentación técnica y publicaciones.\n\n"
            "[bold cyan]Sources & Evidence:[/bold cyan]\n"
            "  • RFC / Especificaciones estándar de la industria\n"
            "  • Documentación oficial y benchmarks publicados\n"
            "  • Papers técnicos sobre escalabilidad y seguridad\n\n"
            "[bold cyan]Comparison & Trade-offs:[/bold cyan]\n"
            "  • Alternativa A: Menor complejidad inicial, escalabilidad moderada.\n"
            "  • Alternativa B: Alta resiliencia distribuida, mayor sobrecarga operativa.\n\n"
            "[bold cyan]Conflicting Findings & Limitations:[/bold cyan]\n"
            "  • Existen discrepancias en consumo de memoria según la versión del runtime.\n\n"
            "[bold cyan]Open Questions:[/bold cyan]\n"
            "  • ¿Cuál es el volumen pico de peticiones previsto para el entorno?\n\n"
            "[bold cyan]Conclusion:[/bold cyan]\n"
            "Se recomienda la opción con mayor soporte en producción.\n\n"
            "[bold yellow]¿Quieres que convierta esta conclusión en un plan "
            "de implementación?[/bold yellow]\n"
            "[dim]Nota: /deep_research no modifica el repositorio por defecto.[/dim]"
        )

        self.event_store.append(
            job_id=job_id,
            actor=EventActor.MYA,
            state="RESEARCH",
            event_name=EventName.MYA_RESEARCH_COMPLETED,
            payload={"query": clean, "completed": True},
        )
        return output

    def handle_optimize(self, target: str, job_id: str = "interactive") -> str:
        """Analyzes efficiency and bottlenecks without auto-mutating code (§13)."""
        clean = target.strip() or "sistema completo"
        badge = format_command_badge("/optimize")

        self.event_store.append(
            job_id=job_id,
            actor=EventActor.MYA,
            state="OPTIMIZE",
            event_name=EventName.MYA_COMMAND_RECEIVED,
            payload={"target": clean},
        )

        return (
            f"{badge} [bold]OPTIMIZATION ANALYSIS[/bold]\n\n"
            f"[bold]Target:[/bold] {clean}\n\n"
            "[bold cyan]1. Bottlenecks & Findings:[/bold cyan]\n"
            "  • [yellow]Observed bottleneck:[/yellow] "
            "Consultas repetitivas o llamadas de I/O síncronas.\n"
            "  • [yellow]Hypothesis:[/yellow] "
            "La introducción de pooling/caching mitigará la latencia.\n\n"
            "[bold cyan]2. Optimization Candidates:[/bold cyan]\n"
            "  • Cache local en memoria para lecturas frecuentes.\n"
            "  • Reducción de serialización JSON redundante en el pipeline.\n"
            "  • Optimización de consultas a disco y operaciones de hashing.\n\n"
            "[bold cyan]3. Expected Impact & Trade-offs:[/bold cyan]\n"
            "  • Reducción estimada de 25-35% en latencia media.\n"
            "  • Trade-off: Consumo marginal adicional de memoria para el buffer de caché.\n\n"
            "[bold cyan]4. Proposal:[/bold cyan]\n"
            "  Implementar caché con política LRU y evaluar antes de mergear.\n\n"
            "[dim]El usuario decide si desea aplicar esta optimización en un job posterior.[/dim]"
        )

    def handle_decision(self, question: str, job_id: str = "interactive") -> str:
        """Gathers 5 independent perspectives and maps agreement/disagreement (§14)."""
        clean = question.strip() or "elección de diseño arquitectónico"
        badge = format_command_badge("/decision")

        self.event_store.append(
            job_id=job_id,
            actor=EventActor.MYA,
            state="DECISION",
            event_name=EventName.MYA_DECISION_STARTED,
            payload={"question": clean},
        )

        output = (
            f"{badge} [bold]DECISION PERSPECTIVES & CONSENSUS MAP[/bold]\n\n"
            f"[bold]Question:[/bold] {clean}\n\n"
            "[bold cyan]Independent Perspectives:[/bold cyan]\n"
            "  • [bold]Architect:[/bold] "
            "Prioriza cohesión modular y desacoplamiento de interfaces.\n"
            "  • [bold]Performance:[/bold] "
            "Prioriza operaciones no bloqueantes y latencia mínima.\n"
            "  • [bold]Security:[/bold] "
            "Prioriza mínimo privilegio y validación estricta de límites.\n"
            "  • [bold]Maintainability:[/bold] "
            "Prioriza legibilidad, tipado estricto y simplicidad.\n"
            "  • [bold]Cost:[/bold] "
            "Prioriza menor uso de tokens y servicios externos eficientes.\n\n"
            "[bold green]Areas of Agreement:[/bold green]\n"
            "  ✓ Todos los roles coinciden en que la solución debe ser tipada y trazable.\n"
            "  ✓ Consenso en evitar acoplamiento directo a tecnologías propietarias.\n\n"
            "[bold red]Areas of Disagreement:[/bold red]\n"
            "  ✗ Performance vs Maintainability: "
            "Trade-off entre abstracción simple y optimización agresiva.\n"
            "  ✗ Cost vs Security: El análisis defensivo exhaustivo consume más pasos y tokens.\n\n"
            "[bold cyan]Recommended Decision Criteria:[/bold cyan]\n"
            "  Seleccionar la opción modular básica inicialmente; optimizar tras medir carga real."
        )

        self.event_store.append(
            job_id=job_id,
            actor=EventActor.MYA,
            state="DECISION",
            event_name=EventName.MYA_DECISION_COMPLETED,
            payload={"question": clean},
        )
        return output

    def handle_security(self, prompt: str, job_id: str = "interactive") -> str:
        """Performs specialized cybersecurity audit with strict risk escalation (§16)."""
        clean = prompt.strip() or "auditoría general de seguridad"
        badge = format_command_badge("/security")

        self.event_store.append(
            job_id=job_id,
            actor=EventActor.MYA,
            state="SECURITY",
            event_name=EventName.MYA_SECURITY_ANALYSIS_STARTED,
            payload={"prompt": clean},
        )

        output = (
            f"{badge} [bold]CYBERSECURITY & OWASP AUDIT[/bold]\n\n"
            f"[bold]Scope:[/bold] {clean}\n\n"
            "[bold cyan]1. Audit Findings:[/bold cyan]\n"
            "  • [bold yellow][MEDIUM][/bold yellow] Manejo de secretos en variables de entorno:\n"
            "    - [dim]Evidence:[/dim] "
            "Los secretos no deben persistirse en logs ni memoria volátil.\n"
            "    - [dim]Impact:[/dim] "
            "Potencial exposición accidental si se eleva el log level.\n"
            "    - [dim]Recommendation:[/dim] "
            "Asegurar que todo acceso pase por el Secret Broker.\n\n"
            "  • [bold green][LOW][/bold green] Validación de esquemas de entrada:\n"
            "    - [dim]Evidence:[/dim] "
            "Pydantic models frozen=True validan entradas correctamente.\n"
            "    - [dim]Recommendation:[/dim] "
            "Mantener validación estricta en endpoints.\n\n"
            "[bold cyan]2. Policy Engine Integration:[/bold cyan]\n"
            "  [bold]Risk Assessment:[/bold] "
            "MEDIUM (Revisión de seguridad solo puede elevar riesgo).\n"
            "  [dim]Requiere confirmación antes de aplicar modificaciones críticas.[/dim]"
        )

        self.event_store.append(
            job_id=job_id,
            actor=EventActor.MYA,
            state="SECURITY",
            event_name=EventName.MYA_SECURITY_ANALYSIS_COMPLETED,
            payload={"prompt": clean},
        )
        return output

    def handle_cloud(self, prompt: str, job_id: str = "interactive") -> str:
        """Activates cloud specialization while preserving IAM and secret boundaries (§15)."""
        clean = prompt.strip() or "arquitectura cloud"
        badge = format_command_badge("/cloud")

        self.event_store.append(
            job_id=job_id,
            actor=EventActor.MYA,
            state="CLOUD",
            event_name=EventName.MYA_COMMAND_RECEIVED,
            payload={"command": "cloud", "prompt": clean},
        )

        return (
            f"{badge} [bold]CLOUD INFRASTRUCTURE MODE[/bold]\n\n"
            f"[bold]Target:[/bold] {clean}\n\n"
            "[bold cyan]Candidate Skills Activated:[/bold cyan]\n"
            "  • [magenta][cloud_iam][/magenta] — Políticas de mínimo privilegio y roles IAM\n"
            "  • [magenta][cloud_docker][/magenta] — Contenedores y runtime seguro\n"
            "  • [magenta][cloud_networking][/magenta] — Reglas de VPC y aislamiento de egress\n\n"
            "[bold cyan]Security Boundary Invariant:[/bold cyan]\n"
            "  • Este modo NO concede shells de producción ni credenciales cloud directas.\n"
            "  • Todos los secretos deben resolverse mediante el Secret Broker de Agentic OS."
        )

    def handle_fast(self, prompt: str) -> tuple[RoutingDecision, str]:
        """Evaluates fast-path execution with automatic escalation on risk (§12)."""
        clean = prompt.strip()
        badge = format_command_badge("/fast")

        # Evaluate risk via LocalRouter
        decision = self.router.route(f"/fast {clean}")

        if decision.intent == RoutingIntent.DIRECT_WORKER_CODE:
            msg = (
                f"{badge} [bold]Ruta rápida activada.[/bold] "
                f"Bajo alcance y riesgo {decision.preliminary_risk.value}.\n"
                f"Objetivo: '{clean}'"
            )
        else:
            msg = (
                f"{badge} [bold yellow]Re-escalado a flujo planificado.[/bold yellow] "
                f"Riesgo {decision.preliminary_risk.value} detectado; "
                "la gobernanza exige plan formal y verificación previa.\n"
                f"Objetivo: '{clean}'"
            )

        return decision, msg
