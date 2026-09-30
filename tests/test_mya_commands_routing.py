from pathlib import Path

from myagentos.cli import cmd_mya
from myagentos.core.models.risk import RiskLevel
from myagentos.router.models import RoutingIntent
from myagentos.router.rules import LocalRouter
from myagentos.ui.commands import SlashCommandKind, parse_input


def test_slash_command_parsing():
    c_info = parse_input("/info")
    assert c_info.kind == SlashCommandKind.INFO

    c_telemetry = parse_input("/telemetry")
    assert c_telemetry.kind == SlashCommandKind.TELEMETRY

    c_monitor = parse_input("/monitor")
    assert c_monitor.kind == SlashCommandKind.MONITOR

    c_fast = parse_input("/fast arregla este test")
    assert c_fast.kind == SlashCommandKind.FAST
    assert c_fast.argument == "arregla este test"

    c_sci = parse_input("/sci_mode formula una hipótesis")
    assert c_sci.kind == SlashCommandKind.SCI_MODE
    assert c_sci.argument == "formula una hipótesis"

    c_deep = parse_input("/deep_research compara Kafka y RabbitMQ")
    assert c_deep.kind == SlashCommandKind.DEEP_RESEARCH
    assert c_deep.argument == "compara Kafka y RabbitMQ"

    c_opt = parse_input("/optimize reduce el uso de memoria")
    assert c_opt.kind == SlashCommandKind.OPTIMIZE
    assert c_opt.argument == "reduce el uso de memoria"

    c_dec = parse_input("/decision ¿JWT o sesiones?")
    assert c_dec.kind == SlashCommandKind.DECISION
    assert c_dec.argument == "¿JWT o sesiones?"

    c_cloud = parse_input("/cloud prepara terraform")
    assert c_cloud.kind == SlashCommandKind.CLOUD
    assert c_cloud.argument == "prepara terraform"

    c_sec = parse_input("/security revisa injection en SQL")
    assert c_sec.kind == SlashCommandKind.SECURITY
    assert c_sec.argument == "revisa injection en SQL"


def test_router_integration():
    router = LocalRouter()

    # /fast
    d1 = router.route("/fast typo fix")
    assert d1.intent == RoutingIntent.DIRECT_WORKER_CODE

    # /fast with high risk -> escalated to PLANNED_CODE
    d2 = router.route("/fast drop table users and restart production")
    assert d2.intent == RoutingIntent.PLANNED_CODE
    assert d2.preliminary_risk >= RiskLevel.MEDIUM

    # /deep_research
    d3 = router.route("/deep_research state of LLM agents")
    assert d3.intent == RoutingIntent.DEEP_RESEARCH

    # /sci_mode
    d4 = router.route("/sci_mode evaluate statistical significance")
    assert d4.intent == RoutingIntent.DEEP_RESEARCH

    # /security -> PLANNED_CODE with minimum MEDIUM risk
    d5 = router.route("/security audit auth middleware")
    assert d5.intent == RoutingIntent.PLANNED_CODE
    assert d5.preliminary_risk >= RiskLevel.MEDIUM

    # /optimize
    d6 = router.route("/optimize cache layer")
    assert d6.intent == RoutingIntent.PLANNED_CODE

    # /cloud
    d7 = router.route("/cloud deploy ECS cluster")
    assert d7.intent == RoutingIntent.PLANNED_CODE


def test_cli_cmd_mya(capsys, tmp_path: Path):
    cmd_mya("/info", repo_path=str(tmp_path))
    out_info = capsys.readouterr().out
    assert "SESSION INFORMATION" in out_info

    cmd_mya("/telemetry", repo_path=str(tmp_path))
    out_tele = capsys.readouterr().out
    assert "AGENT TELEMETRY" in out_tele

    cmd_mya("/monitor", repo_path=str(tmp_path))
    out_mon = capsys.readouterr().out
    assert "AGENTIC OS · LIVE MONITOR" in out_mon

    cmd_mya("/decision", argument="SQL vs NoSQL", repo_path=str(tmp_path))
    out_dec = capsys.readouterr().out
    assert "DECISION PERSPECTIVES" in out_dec

    cmd_mya("/security", argument="audit auth", repo_path=str(tmp_path))
    out_sec = capsys.readouterr().out
    assert "CYBERSECURITY & OWASP AUDIT" in out_sec
