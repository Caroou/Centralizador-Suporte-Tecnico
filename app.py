from __future__ import annotations

import json
import os
import re
import time
import sqlite3
import base64
import hashlib
import hmac
import secrets
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

load_dotenv()
ROOT = Path(__file__).parent
DB_PATH = Path(os.getenv("DATABASE_PATH", str(ROOT / "centralizador.db")))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
app = FastAPI(title="Centralizador de Soluções e Diagnósticos", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
SESSION_COOKIE = "centralizador_session"
SESSION_DAYS = 7
ENCRYPTED_PREFIX = "enc:v1:"
ENCRYPTED_FIELDS = {
    "tickets": ("modelo_notebook", "sintoma_principal", "testes_ja_feitos", "observacoes_iniciais", "causa_ou_solucao", "part_numbers_confirmados", "diagnostico_atual"),
    "ticket_steps": ("teste", "observacao"),
    "knowledge": ("modelo_notebook", "sintoma_principal", "teste", "causa_ou_solucao", "part_numbers_confirmados"),
}

GENERAL_KB_VERSION = "common-hardware-guides-2026-11-v1"
GENERAL_KB_SEED = [
    ("notebook", "Sem energia / não liga", "Sem sinal de energia; não liga, sem LEDs ou só liga no carregador",
     "Causas frequentes: tomada/extensão, cabo, adaptador, conector DC ou bateria. Verifique tomada e conexões, observe LED do adaptador, confira o modelo e a potência exigidos e teste um adaptador compatível conhecido. Reset elétrico somente se o manual do modelo orientar. Se persistir, diagnosticar adaptador/conector/placa em bancada. Referências: https://support.hp.com/us-en/document/ish_2025983-1502949-16 e https://www.dell.com/support/kbdoc/en-us/000125609/resolve-no-power-no-post-no-boot-or-no-video-issues-with-your-dell-computer"),
    ("notebook", "Tela preta / sem imagem", "Liga mas fica sem imagem, tela preta, display não mostra vídeo",
     "Primeiro determine se o equipamento completou o POST: observe LEDs/códigos e teste monitor externo, entrada e cabo conhecidos. Se houver imagem externa, priorize painel, cabo de vídeo, brilho ou driver; sem imagem em ambos, investigar POST, memória ou vídeo integrado conforme manual. Não condene tela ou placa sem isolar a falha. Referência: https://support.hp.com/gb-en/document/ish_7096250-7096363-16"),
    ("notebook", "Bateria não carrega", "Bateria não carrega, descarrega rápido ou notebook só funciona na fonte",
     "Causas frequentes: fonte/cabo inadequados, mau contato, limite de carga configurado, bateria degradada ou conector. Conferir LED/estado da fonte, conexão e diagnóstico de bateria do fabricante; comparar com fonte compatível conhecida, respeitando tensão e potência. Bateria estufada, aquecendo ou danificada: interromper uso e encaminhar para serviço; não pressionar nem perfurar. Referência: https://support.hp.com/us-en/document/ish_2025983-1502949-16"),
    ("notebook", "Windows não inicia", "Não inicia o Windows, trava no logo ou mostra reparo automático",
     "Separe falha de POST de falha do sistema operacional e confirme se o SSD aparece no BIOS/UEFI e nos diagnósticos do fabricante. Se o armazenamento for detectado e saudável, use o Reparo de Inicialização do WinRE; confirme antes a chave BitLocker e preserve os dados. Se o disco não for detectado ou falhar no diagnóstico, faça backup/recuperação antes de reinstalar ou substituir. Referência: https://support.microsoft.com/en-us/windows/experience/startup-boot/startup-repair"),
    ("notebook", "Aquecimento / desligamento", "Aquece demais, ventoinha alta, reduz desempenho ou desliga por temperatura",
     "Causas comuns: entradas de ar obstruídas, uso sobre tecido, poeira, ventoinha degradada ou carga alta. Reproduza em superfície rígida, confira temperatura/carga e diagnóstico do fabricante, verifique ruído/fluxo de ar sem abrir o aparelho. Persistindo, limpeza interna, ventoinha e conjunto térmico exigem procedimento e pasta térmica adequados em bancada; não indique peça antes de confirmar falha. Referência geral: https://www.dell.com/support/kbdoc/en-us/000125609/resolve-no-power-no-post-no-boot-or-no-video-issues-with-your-dell-computer"),
    ("notebook", "Lentidão / travamentos", "Notebook lento, congelando ou reiniciando sem causa aparente",
     "Verifique espaço livre, uso de CPU/memória/disco, programas de inicialização, atualizações recentes e alertas no Gerenciador de Dispositivos. Faça diagnóstico de memória/armazenamento do fabricante e backup se houver alerta de saúde do SSD. Drivers, pouco espaço ou processo em segundo plano são causas frequentes; só cogite troca após erro reproduzível em diagnóstico. Referência: https://support.microsoft.com/en-us/windows/experience/performance-optimization/troubleshooting-windows-unexpected-restarts-and-stop-code-errors"),
    ("notebook", "Wi-Fi não conecta", "Wi-Fi ausente, não conecta ou cai com frequência",
     "Confirme modo avião, tecla/chave física, se outras redes aparecem e se outro dispositivo conecta à mesma rede. Reinicie roteador e computador somente se apropriado, verifique adaptador/estado no Gerenciador de Dispositivos e instale driver do fabricante do modelo. Teste outra rede para separar problema do notebook do roteador; substituição de placa só após diagnóstico e antenas/conexões verificados."),
    ("desktop", "Sem energia / não liga", "Desktop sem sinal de energia, sem LED ou ventoinhas",
     "Causas comuns: tomada, cabo, filtro/UPS, chave traseira da fonte, fonte ou curto em componente. Teste tomada e cabo conhecidos, bypass seguro de filtro/UPS e observe LEDs. Teste BIST da fonte apenas se o modelo tiver esse recurso e conforme manual. Nunca abra a fonte; isolamento de cabos/componentes requer técnico, energia desconectada e procedimento do fabricante. Referências: https://www.dell.com/support/kbdoc/en-us/000125609/resolve-no-power-no-post-no-boot-or-no-video-issues-with-your-dell-computer e https://www.dell.com/support/kbdoc/en-us/000125185/how-to-troubleshoot-the-power-supply-unit-psu-of-a-dell-desktop-computer"),
    ("desktop", "Falha de POST", "Liga mas não completa POST, fica no logo, apita ou pisca LED de diagnóstico",
     "Registre padrão exato de bipes/LED e consulte o manual do modelo; códigos variam por placa. Remova periféricos externos e tente inicialização mínima. Técnico pode reseat/testar memória um módulo por vez com cabo de energia removido e proteção ESD, respeitando slots recomendados. Se persistir, isole RAM, GPU, fonte e placa por diagnóstico; não troque motherboard por tentativa. Referência: https://www.dell.com/support/kbdoc/en-us/000125609/resolve-no-power-no-post-no-boot-or-no-video-issues-with-your-dell-computer"),
    ("desktop", "Liga sem vídeo", "Desktop liga e ventoinhas giram, mas monitor não mostra imagem",
     "Verifique energia do monitor, entrada selecionada, cabo e teste com monitor/cabo conhecidos. Confirme se o cabo está na saída da GPU dedicada quando instalada, e não numa saída de placa-mãe sem vídeo integrado ativo. Observe se há imagem durante POST e códigos de diagnóstico. Só então isole GPU, memória e monitor com componentes conhecidos. Referência: https://www.dell.com/support/kbdoc/en-us/000125609/resolve-no-power-no-post-no-boot-or-no-video-issues-with-your-dell-computer"),
    ("desktop", "Não encontra o disco / não inicia Windows", "Sem dispositivo de boot, SSD não aparece ou Windows não inicia",
     "Confirme detecção do SSD no UEFI e rode diagnóstico do fabricante. Verifique cabo SATA/energia ou encaixe M.2 somente com o equipamento desligado e desconectado, por técnico. Preserve dados: não inicialize, formate ou reinstale se houver suspeita de falha. Com disco saudável, tente Reparo de Inicialização do Windows e tenha a chave BitLocker à mão. Referência: https://support.microsoft.com/en-us/windows/experience/startup-boot/startup-repair"),
    ("desktop", "Superaquecimento / ruído", "Desktop aquece, ventoinha faz ruído, reduz desempenho ou desliga",
     "Causas frequentes: filtros/entradas obstruídos, ventoinha parada, fluxo de ar ruim ou carga elevada. Confira temperaturas, funcionamento das ventoinhas e fluxo externo; limpe filtro acessível com equipamento desligado. Inspeção interna e limpeza exigem cabo removido e cuidado ESD. Nunca abra a fonte. Persistindo, diagnostique ventoinha e refrigeração antes de recomendar troca."),
    ("desktop", "Tela azul / reinício inesperado", "Tela azul, travamento ou reinício durante uso",
     "Registre código de parada e momento do erro; investigue hardware/driver instalado recentemente, espaço livre, temperatura, memória e saúde do SSD. Use inicialização segura e diagnósticos de fabricante para isolar; faça backup. Atualize ou reverta driver relacionado quando houver evidência. Troca de peça somente após erro consistente em teste. Referência: https://support.microsoft.com/en-us/windows/experience/performance-optimization/troubleshooting-windows-unexpected-restarts-and-stop-code-errors"),
    ("desktop", "Rede cabeada sem conexão", "Ethernet sem internet, link ausente ou conexão cai",
     "Verifique LED da porta, cabo e porta do roteador/switch com outro equipamento. Confirme estado do adaptador e driver no sistema; teste outra porta/rede para separar falha local da rede. Se não houver link com cabo e porta conhecidos, examine conector e NIC conforme manual antes de indicar placa de rede."),
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def encryption_key() -> bytes:
    encoded = os.getenv("DATA_ENCRYPTION_KEY", "").strip()
    if not encoded:
        raise RuntimeError("DATA_ENCRYPTION_KEY ausente. Configure a chave no .env antes de iniciar.")
    try:
        key = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except Exception as exc:
        raise RuntimeError("DATA_ENCRYPTION_KEY não está em Base64 URL-safe válido.") from exc
    if len(key) != 32:
        raise RuntimeError("DATA_ENCRYPTION_KEY deve representar exatamente 32 bytes.")
    return key


def encrypt_text(value: str | None) -> str | None:
    if value is None or value.startswith(ENCRYPTED_PREFIX):
        return value
    nonce = secrets.token_bytes(12)
    cipher = AESGCM(encryption_key()).encrypt(nonce, value.encode("utf-8"), None)
    return ENCRYPTED_PREFIX + base64.urlsafe_b64encode(nonce + cipher).decode("ascii")


def decrypt_text(value: str | None) -> str | None:
    if value is None or not value.startswith(ENCRYPTED_PREFIX):
        return value
    try:
        raw = base64.urlsafe_b64decode(value[len(ENCRYPTED_PREFIX):])
        return AESGCM(encryption_key()).decrypt(raw[:12], raw[12:], None).decode("utf-8")
    except (InvalidTag, ValueError) as exc:
        raise RuntimeError("Não foi possível descriptografar os dados. Verifique se DATA_ENCRYPTION_KEY é a chave original.") from exc


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**15, r=8, p=3, maxmem=64*1024*1024, dklen=32)
    return "scrypt$32768$8$3$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(derived).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$", 5)
        if algo != "scrypt": return False
        salt = base64.urlsafe_b64decode(salt_b64)
        expected = base64.urlsafe_b64decode(hash_b64)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), maxmem=64*1024*1024, dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


@contextmanager
def db():
    if DATABASE_URL:
        import psycopg

        conn = psycopg.connect(DATABASE_URL, row_factory=pg_row, prepare_threshold=None, sslmode="require")
        connection = PostgresConnection(conn)
    else:
        if os.getenv("RENDER"):
            raise RuntimeError("DATABASE_URL ausente no Render. Configure a conexão PostgreSQL do Supabase antes de iniciar.")
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        connection = conn
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


class DBRow(dict):
    """PostgreSQL row with the same key and numeric access as sqlite3.Row."""
    def __getitem__(self, key):
        if isinstance(key, int):
            key = tuple(self.keys())[key]
        return super().__getitem__(key)


def pg_row(cursor, values):
    return DBRow((column.name, value) for column, value in zip(cursor.description, values))


class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, parameters=()):
        return self.connection.execute(statement.replace("?", "%s"), parameters)

    def executescript(self, script):
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self):
        self.connection.commit()

    def close(self):
        self.connection.close()


def table_columns(connection, table: str) -> set[str]:
    if DATABASE_URL:
        rows = connection.execute(
            "SELECT column_name AS name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?",
            (table,),
        ).fetchall()
    else:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def integrity_errors():
    if DATABASE_URL:
        import psycopg
        return (sqlite3.IntegrityError, psycopg.IntegrityError)
    return (sqlite3.IntegrityError,)


def init_db() -> None:
    encryption_key()  # fail closed if no key is configured; never store new data in plaintext
    with db() as c:
        schema = """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'technician' CHECK(role IN ('admin','technician')),
          active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          csrf_token TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS login_attempts (
          attempt_key TEXT PRIMARY KEY,
          failures INTEGER NOT NULL DEFAULT 0,
          window_started TEXT NOT NULL,
          locked_until TEXT
        );
        CREATE TABLE IF NOT EXISTS tickets (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
          base_scope TEXT NOT NULL DEFAULT 'private' CHECK(base_scope IN ('private','general')),
          tipo_equipamento TEXT NOT NULL DEFAULT 'notebook',
          modelo_notebook TEXT NOT NULL,
          sintoma_principal TEXT NOT NULL,
          testes_ja_feitos TEXT NOT NULL DEFAULT '[]',
          observacoes_iniciais TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'aberto' CHECK(status IN ('aberto','encerrado')),
          desfecho TEXT CHECK(desfecho IN ('resolvido','esgotado_sem_solucao')),
          causa_ou_solucao TEXT NOT NULL DEFAULT '',
          origem_conhecimento TEXT CHECK(origem_conhecimento IN ('ia_sugerida_validada','tecnico_manual')),
          part_numbers_confirmados TEXT NOT NULL DEFAULT '[]',
          diagnostico_atual TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ticket_steps (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
          teste TEXT NOT NULL,
          resultado TEXT NOT NULL CHECK(resultado IN ('passou','falhou','inconclusivo')),
          observacao TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS knowledge (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
          scope TEXT NOT NULL DEFAULT 'private' CHECK(scope IN ('private','general')),
          tipo_equipamento TEXT NOT NULL DEFAULT 'notebook',
          modelo_notebook TEXT NOT NULL,
          sintoma_principal TEXT NOT NULL,
          teste TEXT NOT NULL DEFAULT '',
          resultado TEXT NOT NULL DEFAULT '',
          desfecho TEXT CHECK(desfecho IN ('resolvido','esgotado_sem_solucao')),
          causa_ou_solucao TEXT NOT NULL DEFAULT '',
          origem_conhecimento TEXT NOT NULL CHECK(origem_conhecimento IN ('ia_sugerida_validada','tecnico_manual')),
          part_numbers_confirmados TEXT NOT NULL DEFAULT '[]',
          ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_seed_versions (
          version TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
        CREATE INDEX IF NOT EXISTS idx_knowledge_model ON knowledge(modelo_notebook);
        """
        if DATABASE_URL:
            schema = schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
            schema = schema.replace("INTEGER NOT NULL REFERENCES", "BIGINT NOT NULL REFERENCES")
            schema = schema.replace("INTEGER REFERENCES", "BIGINT REFERENCES")
        c.executescript(schema)
        # Migração aditiva para preservar bancos criados por versões anteriores.
        add_columns = {
            "tickets": {
                "tipo_equipamento": "TEXT NOT NULL DEFAULT 'notebook'",
                "owner_user_id": "INTEGER REFERENCES users(id) ON DELETE CASCADE",
                "base_scope": "TEXT NOT NULL DEFAULT 'private'",
                "diagnostico_atual": "TEXT NOT NULL DEFAULT ''",
            },
            "knowledge": {
                "tipo_equipamento": "TEXT NOT NULL DEFAULT 'notebook'",
                "owner_user_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
                "scope": "TEXT NOT NULL DEFAULT 'private'",
            },
        }
        for table, wanted in add_columns.items():
            columns = table_columns(c, table)
            for name, definition in wanted.items():
                if name not in columns:
                    if DATABASE_URL:
                        definition = definition.replace("INTEGER REFERENCES", "BIGINT REFERENCES")
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tickets_owner ON tickets(owner_user_id,status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_owner_scope ON knowledge(owner_user_id,scope)")
        # Encripta valores legados em texto claro, mantendo o banco operável pelo app.
        for table, fields in ENCRYPTED_FIELDS.items():
            existing = table_columns(c, table)
            fields = [name for name in fields if name in existing]
            if not fields: continue
            for row in c.execute(f"SELECT id,{','.join(fields)} FROM {table}").fetchall():
                values = []
                for name in fields:
                    stored = row[name]
                    if isinstance(stored, str) and stored.startswith(ENCRYPTED_PREFIX):
                        decrypt_text(stored)  # validate the configured key before serving requests
                        values.append(stored)
                    else:
                        values.append(encrypt_text(stored))
                if values != [row[name] for name in fields]:
                    assignments = ",".join(f"{name}=?" for name in fields)
                    c.execute(f"UPDATE {table} SET {assignments} WHERE id=?", (*values, row["id"]))
        bootstrap_user = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "").strip()
        bootstrap_pass = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
        if bootstrap_user and bootstrap_pass and c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            if not valid_username(bootstrap_user) or len(bootstrap_pass) < 12:
                raise RuntimeError("BOOTSTRAP_ADMIN_USERNAME inválido ou BOOTSTRAP_ADMIN_PASSWORD com menos de 12 caracteres.")
            uid = c.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?, 'admin',?) RETURNING id", (bootstrap_user, hash_password(bootstrap_pass), now())).fetchone()["id"]
            c.execute("UPDATE tickets SET owner_user_id=? WHERE owner_user_id IS NULL", (uid,))
            c.execute("UPDATE knowledge SET owner_user_id=? WHERE owner_user_id IS NULL", (uid,))
        if not c.execute("SELECT 1 FROM app_seed_versions WHERE version=?", (GENERAL_KB_VERSION,)).fetchone():
            owner = c.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
            for tipo, titulo, symptom, guidance in GENERAL_KB_SEED:
                c.execute("""INSERT INTO knowledge(owner_user_id,scope,tipo_equipamento,modelo_notebook,sintoma_principal,
                    desfecho,causa_ou_solucao,origem_conhecimento,part_numbers_confirmados,created_at)
                    VALUES(?,'general',?,?,?,NULL,?,'tecnico_manual',?,?)""",
                    (owner["id"] if owner else None, tipo, encrypt_text(f"Referência geral · {titulo}"),
                     encrypt_text(symptom), encrypt_text(guidance), encrypt_text("[]"), now()))
            c.execute("INSERT INTO app_seed_versions(version,applied_at) VALUES(?,?)", (GENERAL_KB_VERSION, now()))


@app.on_event("startup")
def startup() -> None:
    init_db()
    # Também protege cópias locais legadas para que não permaneçam com os mesmos
    # dados sensíveis em texto claro após a migração do banco principal.
    for backup_path in ([] if DATABASE_URL else ROOT.glob("*.backup*.db")):
        try:
            conn = sqlite3.connect(backup_path)
            conn.row_factory = sqlite3.Row
            for table, fields in ENCRYPTED_FIELDS.items():
                exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                if not exists: continue
                columns = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                selected = [field for field in fields if field in columns]
                if not selected: continue
                for row in conn.execute(f"SELECT id,{','.join(selected)} FROM {table}").fetchall():
                    values = [encrypt_text(row[field]) for field in selected]
                    if values != [row[field] for field in selected]:
                        assigns = ",".join(f"{field}=?" for field in selected)
                        conn.execute(f"UPDATE {table} SET {assigns} WHERE id=?", (*values,row["id"]))
            conn.commit()
            conn.close()
        except sqlite3.Error:
            continue


def rowdict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    for key in {field for fields in ENCRYPTED_FIELDS.values() for field in fields}:
        if key in d and isinstance(d[key], str):
            d[key] = decrypt_text(d[key])
    for key in ("testes_ja_feitos", "part_numbers_confirmados"):
        if key in d:
            try: d[key] = json.loads(d[key])
            except (ValueError, TypeError): d[key] = []
    return d


def similar_cases(model: str, symptom: str, tipo: str, user_id: int, limit: int = 5) -> list[dict[str, Any]]:
    words = [w for w in re.findall(r"[\w-]+", symptom.lower()) if len(w) > 3][:8]
    with db() as c:
        rows = c.execute("""SELECT id,tipo_equipamento,modelo_notebook,sintoma_principal,desfecho,causa_ou_solucao,
                part_numbers_confirmados,base_scope,owner_user_id,updated_at FROM tickets WHERE status='encerrado'
                AND tipo_equipamento=? AND desfecho IN ('resolvido','esgotado_sem_solucao')
                AND (base_scope='general' OR owner_user_id=?) ORDER BY updated_at DESC""", (tipo, user_id)).fetchall()
    matches = []
    for raw in rows:
        case = rowdict(raw)
        same_model = case["modelo_notebook"].strip().casefold() == model.strip().casefold()
        same_symptom = any(word in case["sintoma_principal"].casefold() for word in words)
        if same_model or same_symptom:
            matches.append({key:case[key] for key in ("id","tipo_equipamento","modelo_notebook","sintoma_principal","desfecho","causa_ou_solucao","part_numbers_confirmados")})
            if len(matches) >= limit: break
    return matches


def general_guides(symptom: str, tipo: str, limit: int = 4) -> list[dict[str, str]]:
    words = {w for w in re.findall(r"[\w-]+", symptom.casefold()) if len(w) > 3}
    if not words: return []
    with db() as c:
        rows = c.execute("SELECT * FROM knowledge WHERE scope='general' AND tipo_equipamento=? ORDER BY created_at DESC", (tipo,)).fetchall()
    ranked = []
    for raw in rows:
        entry = rowdict(raw)
        if not entry["modelo_notebook"].startswith("Referência geral · "): continue
        searchable = f"{entry['modelo_notebook']} {entry['sintoma_principal']} {entry['causa_ou_solucao']}".casefold()
        matched = sum(1 for word in words if word in searchable)
        if matched:
            ranked.append((matched, {"sintoma":entry["sintoma_principal"], "orientacao":entry["causa_ou_solucao"]}))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in ranked[:limit]]


def current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token: raise HTTPException(401, "Faça login para continuar.")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with db() as c:
        row = c.execute("""SELECT u.id,u.username,u.role,u.active,s.csrf_token,s.expires_at
                          FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?""", (token_hash,)).fetchone()
    if not row or not row["active"] or row["expires_at"] <= now():
        raise HTTPException(401, "Sua sessão expirou. Entre novamente.")
    return dict(row)


def authenticated_write(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied or not hmac.compare_digest(supplied, user["csrf_token"]):
        raise HTTPException(403, "Sessão inválida para esta operação. Atualize a página e tente novamente.")
    return user


def admin_user(user: dict[str, Any] = Depends(authenticated_write)) -> dict[str, Any]:
    if user["role"] != "admin": raise HTTPException(403, "Somente a administradora pode gerenciar usuários.")
    return user


def admin_reader(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user["role"] != "admin": raise HTTPException(403, "Somente a administradora pode consultar os usuários.")
    return user


def new_session(user_id: int, response: Response) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    expiry = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    with db() as c:
        c.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)",
                  (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf, expiry, now()))
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
                        samesite="strict", max_age=SESSION_DAYS * 86400, path="/")
    return token, csrf


def valid_username(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", name))


def assign_legacy_data(user_id: int, conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE tickets SET owner_user_id=? WHERE owner_user_id IS NULL", (user_id,))
    conn.execute("UPDATE knowledge SET owner_user_id=? WHERE owner_user_id IS NULL", (user_id,))


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=128)


class SetupInput(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=12, max_length=128)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=12, max_length=128)


class UserStatusUpdate(BaseModel):
    active: bool


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class CloseInput(BaseModel):
    desfecho: str
    causa_ou_solucao: str = Field(min_length=1)
    origem_conhecimento: str
    part_numbers_confirmados: list[str] = []
    base_scope: str = "private"


class TicketCreate(BaseModel):
    tipo_equipamento: str = "notebook"
    modelo_notebook: str = Field(min_length=1)
    sintoma_principal: str = Field(min_length=1)
    testes_ja_feitos: list[str] = []
    observacoes_iniciais: str = ""


class StepInput(BaseModel):
    teste: str = Field(min_length=1)
    resultado: str
    observacao: str = ""


class KnowledgeUpdate(BaseModel):
    tipo_equipamento: str = "notebook"
    scope: str = "private"
    modelo_notebook: str
    sintoma_principal: str
    teste: str = ""
    resultado: str = ""
    desfecho: str | None = None
    causa_ou_solucao: str = ""
    origem_conhecimento: str
    part_numbers_confirmados: list[str] = []


def get_ticket(ticket_id: int, user_id: int | None = None) -> dict[str, Any]:
    with db() as c:
        if user_id is None:
            row = c.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        else:
            row = c.execute("SELECT * FROM tickets WHERE id=? AND owner_user_id=?", (ticket_id, user_id)).fetchone()
        if not row: raise HTTPException(404, "Chamado não encontrado")
        ticket = rowdict(row)
        try:
            ticket["diagnostico_atual"] = json.loads(ticket["diagnostico_atual"]) if ticket.get("diagnostico_atual") else None
        except (ValueError, TypeError):
            ticket["diagnostico_atual"] = None
        ticket["etapas"] = [rowdict(x) for x in c.execute("SELECT * FROM ticket_steps WHERE ticket_id=? ORDER BY id", (ticket_id,))]
    return ticket


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/healthz")
def health_check():
    with db() as c:
        c.execute("SELECT 1").fetchone()
    return {"status":"ok"}


@app.get("/api/auth/status")
def auth_status():
    with db() as c:
        count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return {"setup_required": count == 0}


@app.post("/api/auth/setup")
def initial_setup(data: SetupInput, request: Request, response: Response):
    if not request.client or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(403, "A configuração inicial só pode ser feita localmente.")
    if not valid_username(data.username): raise HTTPException(400, "Use de 3 a 40 caracteres: letras, números, ponto, hífen ou sublinhado.")
    with db() as c:
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
            raise HTTPException(409, "A configuração inicial já foi concluída.")
        user_id = c.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?, 'admin',?) RETURNING id", (data.username, hash_password(data.password), now())).fetchone()["id"]
        assign_legacy_data(user_id, c)
    _, csrf = new_session(user_id, response)
    return {"user":{"id":user_id,"username":data.username,"role":"admin"},"csrf_token":csrf}


@app.post("/api/auth/login")
def login(data: LoginInput, request: Request, response: Response):
    remote = request.client.host if request.client else "unknown"
    attempt_key = hashlib.sha256(f"{remote}:{data.username.casefold()}".encode()).hexdigest()
    rejection = None
    user = None
    with db() as c:
        c.execute("DELETE FROM sessions WHERE expires_at<=?", (now(),))
        attempt = c.execute("SELECT * FROM login_attempts WHERE attempt_key=?", (attempt_key,)).fetchone()
        if attempt and attempt["locked_until"] and attempt["locked_until"] > now():
            rejection = (429, "Muitas tentativas. Aguarde alguns minutos e tente novamente.")
        else:
            user = c.execute("SELECT id,username,password_hash,role,active FROM users WHERE lower(username)=lower(?)", (data.username,)).fetchone()
            ok = bool(user and user["active"] and verify_password(data.password, user["password_hash"]))
            if not ok:
                started = datetime.fromisoformat(attempt["window_started"]) if attempt else datetime.now(timezone.utc)
                count = (attempt["failures"] + 1) if attempt and datetime.now(timezone.utc)-started < timedelta(minutes=15) else 1
                locked = (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(timespec="seconds") if count >= 5 else None
                c.execute("INSERT INTO login_attempts(attempt_key,failures,window_started,locked_until) VALUES(?,?,?,?) ON CONFLICT(attempt_key) DO UPDATE SET failures=excluded.failures,window_started=excluded.window_started,locked_until=excluded.locked_until",
                          (attempt_key,count,now(),locked))
                rejection = (401, "Usuário ou senha incorretos.")
            else:
                c.execute("DELETE FROM login_attempts WHERE attempt_key=?", (attempt_key,))
    if rejection: raise HTTPException(rejection[0], rejection[1])
    _, csrf = new_session(user["id"], response)
    return {"user":{"id":user["id"],"username":user["username"],"role":user["role"]},"csrf_token":csrf}


@app.get("/api/auth/me")
def auth_me(user: dict[str, Any] = Depends(current_user)):
    return {"user":{"id":user["id"],"username":user["username"],"role":user["role"]},"csrf_token":user["csrf_token"]}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, user: dict[str, Any] = Depends(authenticated_write)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with db() as c: c.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict", secure=os.getenv("COOKIE_SECURE", "false").lower() == "true")
    return {"ok": True}


@app.post("/api/auth/password")
def change_password(data: PasswordChange, response: Response, user: dict[str, Any] = Depends(authenticated_write)):
    with db() as c:
        row = c.execute("SELECT password_hash FROM users WHERE id=? AND active=1", (user["id"],)).fetchone()
        if not row or not verify_password(data.current_password, row["password_hash"]):
            raise HTTPException(400, "A senha atual não confere.")
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(data.new_password),user["id"]))
        c.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    _, csrf = new_session(user["id"], response)
    return {"ok":True,"csrf_token":csrf}


@app.get("/api/auth/users")
def list_users(user: dict[str, Any] = Depends(admin_reader)):
    with db() as c:
        return [dict(r) for r in c.execute("""SELECT u.id,u.username,u.role,u.active,u.created_at,
            (SELECT COUNT(*) FROM tickets t WHERE t.owner_user_id=u.id) AS tickets_count,
            (SELECT COUNT(*) FROM knowledge k WHERE k.owner_user_id=u.id) AS knowledge_count
            FROM users u ORDER BY u.id""")]


@app.post("/api/auth/users")
def create_user(data: UserCreate, user: dict[str, Any] = Depends(admin_user)):
    if not valid_username(data.username): raise HTTPException(400, "Use de 3 a 40 caracteres: letras, números, ponto, hífen ou sublinhado.")
    with db() as c:
        try:
            user_id = c.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?, 'technician',?) RETURNING id", (data.username, hash_password(data.password), now())).fetchone()["id"]
        except integrity_errors():
            raise HTTPException(409, "Esse nome de usuário já está em uso.")
        return {"id":user_id,"username":data.username,"role":"technician","active":1}


@app.patch("/api/auth/users/{user_id}")
def update_user_status(user_id: int, data: UserStatusUpdate, user: dict[str, Any] = Depends(admin_user)):
    if user_id == user["id"]:
        raise HTTPException(400, "A conta administradora atual não pode ser desativada por aqui.")
    with db() as c:
        cur = c.execute("UPDATE users SET active=? WHERE id=?", (int(data.active), user_id))
        if cur.rowcount == 0: raise HTTPException(404, "Usuário não encontrado.")
        if not data.active: c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        row = c.execute("SELECT id,username,role,active,created_at FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row)


@app.delete("/api/auth/users/{user_id}")
def delete_user(user_id: int, user: dict[str, Any] = Depends(admin_user)):
    if user_id == user["id"]:
        raise HTTPException(400, "Não é possível excluir a própria conta por aqui.")
    with db() as c:
        target = c.execute("SELECT id,role FROM users WHERE id=?", (user_id,)).fetchone()
        if not target: raise HTTPException(404, "Usuário não encontrado.")
        if target["role"] == "admin": raise HTTPException(400, "A conta administradora não pode ser excluída por aqui.")
        admin = c.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
        if not admin: raise HTTPException(409, "Não há uma conta administradora para preservar a base geral.")
        # O histórico privado é removido junto com o usuário; contribuições
        # públicas são preservadas e passam a ser administradas pela conta admin.
        c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM knowledge WHERE owner_user_id=? AND scope='private'", (user_id,))
        c.execute("UPDATE knowledge SET owner_user_id=? WHERE owner_user_id=? AND scope='general'", (admin["id"], user_id))
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
    return {"ok":True,"id":user_id}


@app.post("/api/tickets")
def create_ticket(data: TicketCreate, user: dict[str, Any] = Depends(authenticated_write)):
    if data.tipo_equipamento not in ("notebook", "desktop"):
        raise HTTPException(400, "Tipo de equipamento inválido")
    stamp = now()
    with db() as c:
        tid = c.execute("INSERT INTO tickets(owner_user_id,base_scope,tipo_equipamento,modelo_notebook,sintoma_principal,testes_ja_feitos,observacoes_iniciais,created_at,updated_at) VALUES(?, 'private', ?,?,?,?,?,?,?) RETURNING id",
                        (user["id"], data.tipo_equipamento, encrypt_text(data.modelo_notebook.strip()), encrypt_text(data.sintoma_principal.strip()), encrypt_text(json.dumps(data.testes_ja_feitos, ensure_ascii=False)), encrypt_text(data.observacoes_iniciais), stamp, stamp))
        tid = tid.fetchone()["id"]
        for test in data.testes_ja_feitos:
            c.execute("INSERT INTO ticket_steps(ticket_id,teste,resultado,observacao,created_at) VALUES(?,?,?,?,?)", (tid, encrypt_text(test), "inconclusivo", encrypt_text("Informado na abertura do chamado"), stamp))
    result = get_ticket(tid, user["id"])
    result["casos_semelhantes"] = similar_cases(data.modelo_notebook, data.sintoma_principal, data.tipo_equipamento, user["id"])
    return result


@app.get("/api/tickets")
def list_tickets(status: str = "aberto", user: dict[str, Any] = Depends(current_user)):
    with db() as c:
        rows = c.execute("SELECT * FROM tickets WHERE status=? AND owner_user_id=? ORDER BY updated_at DESC", (status, user["id"])).fetchall()
    return [rowdict(r) for r in rows]


@app.get("/api/tickets/{ticket_id}")
def ticket_detail(ticket_id: int, user: dict[str, Any] = Depends(current_user)):
    t = get_ticket(ticket_id, user["id"])
    t["casos_semelhantes"] = similar_cases(t["modelo_notebook"], t["sintoma_principal"], t["tipo_equipamento"], user["id"])
    return t


@app.delete("/api/tickets/{ticket_id}")
def delete_ticket(ticket_id: int, user: dict[str, Any] = Depends(authenticated_write)):
    with db() as c:
        cur = c.execute("DELETE FROM tickets WHERE id=? AND owner_user_id=?", (ticket_id, user["id"]))
        if cur.rowcount == 0:
            raise HTTPException(404, "Chamado não encontrado")
    return {"ok": True, "id": ticket_id}


@app.post("/api/tickets/{ticket_id}/steps")
def add_step(ticket_id: int, data: StepInput, user: dict[str, Any] = Depends(authenticated_write)):
    if data.resultado not in ("passou", "falhou", "inconclusivo"):
        raise HTTPException(400, "Resultado inválido")
    with db() as c:
        t = c.execute("SELECT * FROM tickets WHERE id=? AND owner_user_id=? AND status='aberto'", (ticket_id, user["id"])).fetchone()
        if not t: raise HTTPException(404, "Chamado aberto não encontrado")
        tests = json.loads(decrypt_text(t["testes_ja_feitos"]))
        if not any(x.strip().lower() == data.teste.strip().lower() for x in tests): tests.append(data.teste.strip())
        c.execute("UPDATE tickets SET testes_ja_feitos=?,diagnostico_atual='',updated_at=? WHERE id=?", (encrypt_text(json.dumps(tests, ensure_ascii=False)), now(), ticket_id))
        c.execute("INSERT INTO ticket_steps(ticket_id,teste,resultado,observacao,created_at) VALUES(?,?,?,?,?)", (ticket_id, encrypt_text(data.teste.strip()), data.resultado, encrypt_text(data.observacao), now()))
    return get_ticket(ticket_id, user["id"])


@app.post("/api/tickets/{ticket_id}/close")
def close_ticket(ticket_id: int, data: CloseInput, user: dict[str, Any] = Depends(authenticated_write)):
    if data.desfecho not in ("resolvido", "esgotado_sem_solucao") or data.origem_conhecimento not in ("ia_sugerida_validada", "tecnico_manual"):
        raise HTTPException(400, "Desfecho ou origem inválida")
    if data.base_scope not in ("private", "general"):
        raise HTTPException(400, "Base de conhecimento inválida")
    with db() as c:
        t_raw = c.execute("SELECT * FROM tickets WHERE id=? AND owner_user_id=? AND status='aberto'", (ticket_id, user["id"])).fetchone()
        t = rowdict(t_raw)
        if not t: raise HTTPException(404, "Chamado aberto não encontrado")
        c.execute("UPDATE tickets SET status='encerrado',desfecho=?,causa_ou_solucao=?,origem_conhecimento=?,part_numbers_confirmados=?,base_scope=?,updated_at=? WHERE id=?",
                  (data.desfecho, encrypt_text(data.causa_ou_solucao), data.origem_conhecimento, encrypt_text(json.dumps(data.part_numbers_confirmados, ensure_ascii=False)), data.base_scope, now(), ticket_id))
        for s_raw in c.execute("SELECT teste,resultado FROM ticket_steps WHERE ticket_id=?", (ticket_id,)).fetchall():
            s = rowdict(s_raw)
            c.execute("INSERT INTO knowledge(owner_user_id,scope,tipo_equipamento,modelo_notebook,sintoma_principal,teste,resultado,desfecho,causa_ou_solucao,origem_conhecimento,part_numbers_confirmados,ticket_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (user["id"], data.base_scope, t["tipo_equipamento"], encrypt_text(t["modelo_notebook"]), encrypt_text(t["sintoma_principal"]), encrypt_text(s["teste"]), s["resultado"], data.desfecho, encrypt_text(data.causa_ou_solucao), data.origem_conhecimento, encrypt_text(json.dumps(data.part_numbers_confirmados, ensure_ascii=False)), ticket_id, now()))
        c.execute("INSERT INTO knowledge(owner_user_id,scope,tipo_equipamento,modelo_notebook,sintoma_principal,desfecho,causa_ou_solucao,origem_conhecimento,part_numbers_confirmados,ticket_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (user["id"], data.base_scope, t["tipo_equipamento"], encrypt_text(t["modelo_notebook"]), encrypt_text(t["sintoma_principal"]), data.desfecho, encrypt_text(data.causa_ou_solucao), data.origem_conhecimento, encrypt_text(json.dumps(data.part_numbers_confirmados, ensure_ascii=False)), ticket_id, now()))
    return get_ticket(ticket_id, user["id"])


@app.get("/api/knowledge")
def list_knowledge(user: dict[str, Any] = Depends(current_user)):
    with db() as c: rows = c.execute("SELECT * FROM knowledge WHERE scope='general' OR owner_user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
    return [rowdict(r) for r in rows]


@app.put("/api/knowledge/{entry_id}")
def edit_knowledge(entry_id: int, data: KnowledgeUpdate, user: dict[str, Any] = Depends(authenticated_write)):
    if data.origem_conhecimento not in ("ia_sugerida_validada", "tecnico_manual") or (data.desfecho and data.desfecho not in ("resolvido", "esgotado_sem_solucao")):
        raise HTTPException(400, "Dados inválidos")
    with db() as c:
        if data.tipo_equipamento not in ("notebook", "desktop") or data.scope not in ("private", "general"):
            raise HTTPException(400, "Tipo de equipamento inválido")
        current = c.execute("SELECT * FROM knowledge WHERE id=? AND owner_user_id=?", (entry_id,user["id"])).fetchone()
        if not current:
            raise HTTPException(404, "Registro não encontrado")
        cur = c.execute("UPDATE knowledge SET scope=?,tipo_equipamento=?,modelo_notebook=?,sintoma_principal=?,teste=?,resultado=?,desfecho=?,causa_ou_solucao=?,origem_conhecimento=?,part_numbers_confirmados=? WHERE id=?",
            (data.scope,data.tipo_equipamento,encrypt_text(data.modelo_notebook),encrypt_text(data.sintoma_principal),encrypt_text(data.teste),data.resultado,data.desfecho,encrypt_text(data.causa_ou_solucao),data.origem_conhecimento,encrypt_text(json.dumps(data.part_numbers_confirmados, ensure_ascii=False)),entry_id))
        if cur.rowcount == 0: raise HTTPException(404, "Registro não encontrado")
        if current["ticket_id"]:
            c.execute("UPDATE tickets SET base_scope=? WHERE id=? AND owner_user_id=?", (data.scope,current["ticket_id"],current["owner_user_id"]))
            c.execute("UPDATE knowledge SET scope=? WHERE ticket_id=?", (data.scope,current["ticket_id"]))
        return rowdict(c.execute("SELECT * FROM knowledge WHERE id=?", (entry_id,)).fetchone())


SYSTEM_PROMPT = """Você é um assistente de troubleshooting de notebooks e computadores desktop para técnicos. Adapte os procedimentos ao tipo de equipamento informado. Use primeiro as referências da base geral e os casos anteriores fornecidos para evitar pesquisa externa de problemas básicos; não invente certeza e indique quando uma orientação depender do manual exato do modelo. Responda SOMENTE JSON válido com este formato: {\"resumo\":string,\"hipoteses\":[{\"teste\":string,\"motivo\":string,\"complexidade\":string}],\"proximo_passo\":string,\"esgotado\":boolean,\"encaminhamento\":string,\"peca\":{\"necessaria\":boolean,\"nome\":string,\"especificacoes\":[string],\"part_numbers_candidatos\":[string],\"termos_busca\":[string]}}. Forneça no máximo 5 testes em ordem do mais simples/seguro ao mais complexo e indique só um próximo passo. Nunca repita teste realizado, inclusive variações equivalentes. Peças são último recurso: só indique quando as verificações seguras e pertinentes estiverem esgotadas e houver evidência suficiente de qual componente falhou; se ainda houver teste útil, peca.necessaria=false. Ao esgotar opções, esgotado=true e recomende bancada, garantia ou encerramento quando não houver peça isolada. Qualquer part number é apenas candidato e deve ser conferido na etiqueta/manual devido a revisões e conectores. Não faça busca de preços."""


def _llm_call(prompt: dict[str, Any], provider: str, prefix: str, max_tokens: int, timeout_seconds: int) -> dict[str, Any]:
    key = os.getenv(f"{prefix}LLM_API_KEY", "").strip()
    if not key: raise RuntimeError("chave de API ausente")
    if provider == "gemini":
        model = os.getenv(f"{prefix}GEMINI_MODEL", "gemini-3.8-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model)}:generateContent?key={urllib.parse.quote(key)}"
        body = {"systemInstruction":{"parts":[{"text":SYSTEM_PROMPT}]},"contents":[{"role":"user","parts":[{"text":json.dumps(prompt, ensure_ascii=False)}]}],"generationConfig":{"temperature":0.2,"maxOutputTokens":max_tokens,"responseMimeType":"application/json"}}
        headers = {"Content-Type": "application/json"}
    elif provider == "openai_compatible":
        url = os.getenv(f"{prefix}OPENAI_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/") + "/chat/completions"
        body = {"model":os.getenv(f"{prefix}OPENAI_MODEL", "llama-3.3-70b-versatile"),"messages":[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":json.dumps(prompt, ensure_ascii=False)}],"temperature":0.2,"max_tokens":max_tokens,"response_format":{"type":"json_object"}}
        headers = {"Content-Type": "application/json","Authorization":f"Bearer {key}"}
    else: raise RuntimeError("provedor inválido")
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response: payload = json.loads(response.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:220]
        if e.code in (404, 429, 500, 502, 503, 504): raise RuntimeError(f"HTTP {e.code}: {detail}") from e
        raise HTTPException(502, f"O provedor de IA retornou erro ({e.code}). {detail}") from e
    if provider == "gemini":
        candidate = payload.get("candidates", [{}])[0]
        parts = candidate.get("content", {}).get("parts", [])
        content = "\n".join(p.get("text", "") for p in parts if p.get("text") and not p.get("thought", False)).strip()
        if not content: raise ValueError("resposta vazia da IA")
    else:
        content = payload["choices"][0]["message"]["content"]
        if isinstance(content, list): content = "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
        content = str(content).strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE).strip()
    try: parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start_json, end_json = cleaned.find("{"), cleaned.rfind("}")
        if start_json < 0 or end_json < start_json: raise
        parsed = json.loads(cleaned[start_json:end_json + 1])
    if not isinstance(parsed, dict): raise ValueError("a resposta JSON não é um objeto")
    return parsed


def llm_request(prompt: dict[str, Any]) -> dict[str, Any]:
    max_tokens = max(128, min(int(os.getenv("MAX_OUTPUT_TOKENS", "900")), 2000))
    timeout_seconds = max(15, min(int(os.getenv("LLM_TIMEOUT_SECONDS", "120")), 300))
    configs = [("principal", os.getenv("LLM_PROVIDER", "gemini").lower(), "")]
    fallback = os.getenv("FALLBACK_LLM_PROVIDER", "").strip().lower()
    if fallback: configs.append(("reserva", fallback, "FALLBACK_"))
    errors = []
    for label, provider, prefix in configs:
        if not os.getenv(f"{prefix}LLM_API_KEY", "").strip():
            errors.append(f"{label}: chave não configurada")
            continue
        try:
            result = _llm_call(prompt, provider, prefix, max_tokens, timeout_seconds)
            if label == "reserva": result["_provedor_fallback"] = True
            return result
        except HTTPException: raise
        except (TimeoutError, urllib.error.URLError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as e:
            errors.append(f"{label}: {str(e)[:180]}")
    if not any(os.getenv(f"{prefix}LLM_API_KEY", "").strip() for _, _, prefix in configs):
        raise HTTPException(503, "IA não configurada. Informe LLM_API_KEY no arquivo .env.")
    raise HTTPException(503, "Os provedores de IA não responderam. " + "; ".join(errors) + ". Confira as cotas e tente novamente.")

@app.post("/api/tickets/{ticket_id}/next")
def next_step(ticket_id: int, user: dict[str, Any] = Depends(current_user)):
    t = get_ticket(ticket_id, user["id"])
    if t["status"] != "aberto": raise HTTPException(400, "O chamado já foi encerrado")
    prompt = {"chamado":{"tipo_equipamento":t["tipo_equipamento"],"modelo":t["modelo_notebook"],"sintoma_principal":t["sintoma_principal"],"observacoes_iniciais":t["observacoes_iniciais"]},"testes_ja_feitos":t["testes_ja_feitos"],"historico_recente_resumido":[{"teste":x["teste"],"resultado":x["resultado"],"observacao":x["observacao"]} for x in t["etapas"][-12:]],"casos_anteriormente_encerrados":similar_cases(t["modelo_notebook"],t["sintoma_principal"],t["tipo_equipamento"],user["id"],5),"referencias_da_base_geral":general_guides(t["sintoma_principal"],t["tipo_equipamento"],4)}
    answer = llm_request(prompt)
    answer["esgotado"] = answer.get("esgotado") is True
    # Defesa no servidor: não devolver como sugestão um teste que já consta
    # no chamado, mesmo se o modelo ignorar a instrução do prompt.
    done = {re.sub(r"\W+", " ", x).strip().lower() for x in t["testes_ja_feitos"]}
    hypotheses = [h for h in answer.get("hipoteses", [])
                  if re.sub(r"\W+", " ", str(h.get("teste", ""))).strip().lower() not in done]
    answer["hipoteses"] = hypotheses[:5]
    next_name = str(answer.get("proximo_passo", ""))
    if re.sub(r"\W+", " ", next_name).strip().lower() in done:
        answer["proximo_passo"] = hypotheses[0]["teste"] if hypotheses else ""
    if not answer.get("proximo_passo") and not hypotheses:
        answer["esgotado"] = True
        answer["encaminhamento"] = answer.get("encaminhamento") or "Encaminhar para bancada, avaliar garantia ou encerrar após revisão técnica."
    if answer.get("esgotado") is not True:
        answer["peca"] = {"necessaria":False,"nome":"","especificacoes":[],"part_numbers_candidatos":[],"termos_busca":[]}
    with db() as c:
        updated = c.execute("UPDATE tickets SET diagnostico_atual=?,updated_at=? WHERE id=? AND owner_user_id=? AND status='aberto'",
                             (encrypt_text(json.dumps(answer, ensure_ascii=False)), now(), ticket_id, user["id"]))
        if updated.rowcount == 0: raise HTTPException(409, "O chamado foi alterado ou encerrado enquanto o diagnóstico era gerado. Atualize e tente novamente.")
    return answer


@app.post("/api/parts/search")
def parts_search(payload: dict[str, Any], user: dict[str, Any] = Depends(authenticated_write)):
    # URLs de busca construídas a partir dos termos, sem inventar listagens/preços.
    terms = [str(x).strip() for x in payload.get("termos_busca", []) if str(x).strip()][:5]
    if not terms: raise HTTPException(400, "A IA não forneceu termos de busca")
    q = " ".join(terms)
    enc = urllib.parse.quote_plus(q)
    return {"termo":q,"resultados":[{"titulo":f"Pesquisar {q} no Google","loja":"Busca web","preco":None,"url":f"https://www.google.com/search?q={enc}"},{"titulo":f"Pesquisar {q} no Mercado Livre","loja":"Mercado Livre","preco":None,"url":f"https://lista.mercadolivre.com.br/{urllib.parse.quote(q.replace(' ','-'))}"},{"titulo":f"Pesquisar {q} no eBay","loja":"eBay","preco":None,"url":f"https://www.ebay.com/sch/i.html?_nkw={enc}"}]}
