"""`claude -p` arranca limpio y NUNCA con credenciales de API."""
import json
import subprocess
import sys

from apuntes.analisis import claude_cli as C

SONDA = ("import os,json;print(json.dumps({'k':'ANTHROPIC_API_KEY' in os.environ,"
         "'t':'ANTHROPIC_AUTH_TOKEN' in os.environ,'result':'{}'}))")


def test_entorno_sin_credenciales_de_api():
    base = {"ANTHROPIC_API_KEY": "sk-ant-x", "ANTHROPIC_AUTH_TOKEN": "tok", "anthropic_api_key": "y",
            "CLAUDE_CODE_USE_BEDROCK": "1", "PATH": "p", "HOME": "h"}
    env = C.entorno_limpio(base)
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env
    assert not any(k.upper() == "ANTHROPIC_API_KEY" for k in env)
    assert "CLAUDE_CODE_USE_BEDROCK" not in env
    assert env["PATH"] == "p"


def test_el_subproceso_real_no_ve_las_credenciales(monkeypatch):
    """Con las variables puestas en el proceso padre, el hijo lanzado por ClaudeCLI no las ve."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-prueba")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-prueba")
    real = subprocess.run
    resultado = {}

    def falso(cmd, **kw):
        p = real([sys.executable, "-c", SONDA], capture_output=True, text=True, env=kw["env"])
        resultado.update(json.loads(p.stdout))
        return p

    monkeypatch.setattr(C.subprocess, "run", falso)
    try:
        C.ClaudeCLI(exe="claude").completar("s", "u", "haiku")
    except Exception:
        pass
    assert resultado["k"] is False and resultado["t"] is False


def test_comando_limpio():
    cmd = C.construir_comando("claude", "SISTEMA", "haiku", "low")
    assert cmd[:2] == ["claude", "-p"]
    assert "--bare" not in cmd  # --bare exige clave de API: rompería el uso de la licencia
    assert cmd[cmd.index("--tools") + 1] == ""
    for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in cmd
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert cmd[cmd.index("--system-prompt") + 1] == "SISTEMA"
    assert cmd[cmd.index("--model") + 1] == "haiku"
    assert "--mcp-config" not in cmd and "--allowedTools" not in cmd


def test_error_de_sesion_y_de_limite():
    e = C.clasificar_error("Not logged in · Please run /login")
    assert e.tipo == "sesion" and e.bloqueante and "sesión" in e.mensaje and "continúan" in e.mensaje
    e = C.clasificar_error("Claude AI usage limit reached|1760000000")
    assert e.tipo == "limite" and e.bloqueante and "límite" in e.mensaje
    e = C.clasificar_error("5-hour limit reached ∙ resets 3pm")
    assert e.tipo == "limite"
    e = C.clasificar_error("Something odd happened")
    assert e.tipo == "otro" and e.transitorio and not e.bloqueante


def test_interpretar_salida_ok_y_uso():
    d = {"is_error": False, "result": "{\"a\":1}", "duration_ms": 1234,
         "modelUsage": {"claude-haiku-5-5": {"inputTokens": 2, "outputTokens": 47, "cacheReadInputTokens": 5,
                                             "cacheCreationInputTokens": 1029, "costUSD": 0.0002}}}
    r = C.interpretar_salida(json.dumps(d), "", 0, "haiku")
    assert r.texto == '{"a":1}' and r.ms == 1234
    u = r.uso[0]
    assert (u.modelo, u.entrada, u.salida, u.cache_creacion, u.cache_lectura) == ("claude-haiku-5-5", 2, 47, 1029, 5)


def test_interpretar_salida_con_error_de_login():
    d = {"is_error": True, "result": "Not logged in · Please run /login"}
    try:
        C.interpretar_salida(json.dumps(d), "", 1, "haiku")
    except Exception as e:
        assert e.tipo == "sesion"
    else:
        raise AssertionError("debía fallar")


def test_sin_razonamiento_solo_cuando_se_pide_y_sigue_sin_claves():
    base = {"ANTHROPIC_API_KEY": "x", "PATH": "p"}
    assert "MAX_THINKING_TOKENS" not in C.entorno_limpio(base)
    e = C.entorno_limpio(base, sin_razonamiento=True)
    assert e["MAX_THINKING_TOKENS"] == "0" and "ANTHROPIC_API_KEY" not in e


def test_el_subproceso_arranca_sin_ventana_y_con_prioridad_baja(monkeypatch):
    """`claude -p` no compite con Whisper: sin ventana y, en Windows, por debajo de lo normal (en otro sistema, flags 0). No se ejecuta `claude`."""
    capturado = {}

    def falso(cmd, **kw):
        capturado.update(kw)
        raise FileNotFoundError

    monkeypatch.setattr(C.subprocess, "run", falso)
    try:
        C.ClaudeCLI(exe="claude").completar("s", "u", "haiku")
    except Exception:
        pass
    esperado = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    assert capturado["creationflags"] == esperado
    if sys.platform == "win32":
        assert capturado["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert capturado["creationflags"] & subprocess.BELOW_NORMAL_PRIORITY_CLASS
