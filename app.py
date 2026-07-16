import os
import io
import base64
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
import qrcode

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")

# ---------------------------------------------------------------------------
# Configuração do banco de dados
# ---------------------------------------------------------------------------
# Em produção (Render), a variável DATABASE_URL é injetada automaticamente
# ao conectar um banco Postgres ao Web Service. Localmente, sem essa
# variável, o app usa um arquivo SQLite (festa.db) — bom pra testar rápido,
# mas os dados no Render só ficam garantidos usando o Postgres.
db_url = os.environ.get("DATABASE_URL", "sqlite:///festa.db")
if db_url.startswith("postgres://"):
    # Render/Heroku entregam a URL no formato antigo; SQLAlchemy 1.4+ exige postgresql://
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
db = SQLAlchemy(app)


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
class Pessoa(db.Model):
    __tablename__ = "pessoas"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    fone = db.Column(db.String(40))


class Evento(db.Model):
    __tablename__ = "eventos"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(160), nullable=False)
    criado = db.Column(db.String(20), nullable=False)
    valor_total = db.Column(db.Float, nullable=False, default=0)
    pix_chave = db.Column(db.String(140), nullable=False)
    pix_nome = db.Column(db.String(60))
    pix_cidade = db.Column(db.String(40))

    participantes = db.relationship(
        "Participante", backref="evento", cascade="all, delete-orphan", lazy=True
    )


class Participante(db.Model):
    __tablename__ = "participantes"
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey("eventos.id"), nullable=False)
    pessoa_id = db.Column(db.Integer, db.ForeignKey("pessoas.id"), nullable=False)
    pago = db.Column(db.Boolean, nullable=False, default=False)
    pago_em = db.Column(db.String(40))

    pessoa = db.relationship("Pessoa", lazy=True)


with app.app_context():
    db.create_all()


# ---------------------------------------------------------------------------
# Geração do código Pix (BR Code / EMV) — padrão Bacen
# ---------------------------------------------------------------------------
def crc16(payload: str) -> str:
    crc = 0xFFFF
    for ch in payload:
        crc ^= ord(ch) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return format(crc, "04X")


def emv(field_id: str, value: str) -> str:
    return f"{field_id}{len(value):02d}{value}"


def gerar_payload_pix(chave, nome, cidade, valor, descricao=""):
    nome = (nome or "RECEBEDOR")[:25].upper()
    cidade = (cidade or "BRASIL")[:15].upper()
    txid = "***"
    merchant_account = emv("00", "br.gov.bcb.pix") + emv("01", chave)
    if descricao:
        merchant_account += emv("02", descricao[:40])

    payload = (
        emv("00", "01")
        + emv("01", "12")
        + emv("26", merchant_account)
        + emv("52", "0000")
        + emv("53", "986")
    )
    if valor:
        payload += emv("54", f"{float(valor):.2f}")
    payload += (
        emv("58", "BR")
        + emv("59", nome)
        + emv("60", cidade)
        + emv("62", emv("05", txid))
    )
    payload += "6304"
    return payload + crc16(payload)


def qrcode_base64(texto: str) -> str:
    img = qrcode.make(texto)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def participantes_do_evento(evento_id):
    """Retorna a lista de participantes já com os dados da pessoa, ordenada por nome."""
    parts = (
        Participante.query.filter_by(evento_id=evento_id)
        .join(Pessoa)
        .order_by(Pessoa.nome)
        .all()
    )
    return [
        {
            "part_id": p.id,
            "pago": p.pago,
            "pago_em": p.pago_em,
            "pessoa_id": p.pessoa_id,
            "nome": p.pessoa.nome,
            "fone": p.pessoa.fone,
        }
        for p in parts
    ]


# ---------------------------------------------------------------------------
# Rotas — Home
# ---------------------------------------------------------------------------
@app.route("/")
def home():
    eventos = Evento.query.order_by(Evento.id.desc()).all()
    resumo = []
    for ev in eventos:
        total = Participante.query.filter_by(evento_id=ev.id).count()
        pagos = Participante.query.filter_by(evento_id=ev.id, pago=True).count()
        pct = round(100 * pagos / total) if total else 0
        resumo.append({"ev": ev, "total": total, "pagos": pagos, "pct": pct})
    return render_template("home.html", resumo=resumo)


# ---------------------------------------------------------------------------
# Rotas — Pessoas
# ---------------------------------------------------------------------------
@app.route("/pessoas", methods=["GET", "POST"])
def pessoas():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        fone = request.form.get("fone", "").strip()
        if nome:
            db.session.add(Pessoa(nome=nome, fone=fone))
            db.session.commit()
        return redirect(url_for("pessoas"))
    lista = Pessoa.query.order_by(Pessoa.nome).all()
    return render_template("pessoas.html", pessoas=lista)


@app.route("/pessoas/<int:pessoa_id>/excluir", methods=["POST"])
def excluir_pessoa(pessoa_id):
    pessoa = Pessoa.query.get(pessoa_id)
    if pessoa:
        Participante.query.filter_by(pessoa_id=pessoa_id).delete()
        db.session.delete(pessoa)
        db.session.commit()
    return redirect(url_for("pessoas"))


# ---------------------------------------------------------------------------
# Rotas — Criar / editar evento
# ---------------------------------------------------------------------------
@app.route("/eventos/novo", methods=["GET", "POST"])
def novo_evento():
    pessoas_lista = Pessoa.query.order_by(Pessoa.nome).all()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        valor = request.form.get("valor", "0").strip()
        chave = request.form.get("pix_chave", "").strip()
        pix_nome = request.form.get("pix_nome", "").strip()
        pix_cidade = request.form.get("pix_cidade", "").strip()
        participantes_ids = request.form.getlist("participantes")

        if not nome or not chave or not participantes_ids:
            flash("Preencha o nome, a chave Pix e escolha pelo menos uma pessoa.")
            return render_template(
                "criar_evento.html", pessoas=pessoas_lista, evento=None, selecionados=[]
            )

        ev = Evento(
            nome=nome,
            criado=datetime.now().strftime("%d/%m/%Y"),
            valor_total=float(valor or 0),
            pix_chave=chave,
            pix_nome=pix_nome,
            pix_cidade=pix_cidade,
        )
        db.session.add(ev)
        db.session.flush()  # garante ev.id antes de criar os participantes

        for pid in participantes_ids:
            db.session.add(Participante(evento_id=ev.id, pessoa_id=int(pid)))
        db.session.commit()
        return redirect(url_for("ver_evento", evento_id=ev.id))

    return render_template(
        "criar_evento.html", pessoas=pessoas_lista, evento=None, selecionados=[]
    )


@app.route("/eventos/<int:evento_id>/editar", methods=["GET", "POST"])
def editar_evento(evento_id):
    ev = Evento.query.get(evento_id)
    if not ev:
        return redirect(url_for("home"))
    pessoas_lista = Pessoa.query.order_by(Pessoa.nome).all()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        valor = request.form.get("valor", "0").strip()
        chave = request.form.get("pix_chave", "").strip()
        pix_nome = request.form.get("pix_nome", "").strip()
        pix_cidade = request.form.get("pix_cidade", "").strip()
        participantes_ids = set(request.form.getlist("participantes"))

        if not nome or not chave or not participantes_ids:
            flash("Preencha o nome, a chave Pix e escolha pelo menos uma pessoa.")
            selecionados = [str(p["pessoa_id"]) for p in participantes_do_evento(evento_id)]
            return render_template(
                "criar_evento.html", pessoas=pessoas_lista, evento=ev, selecionados=selecionados
            )

        ev.nome = nome
        ev.valor_total = float(valor or 0)
        ev.pix_chave = chave
        ev.pix_nome = pix_nome
        ev.pix_cidade = pix_cidade

        atuais = {str(p.pessoa_id) for p in Participante.query.filter_by(evento_id=evento_id)}
        for pid in atuais - participantes_ids:
            Participante.query.filter_by(evento_id=evento_id, pessoa_id=int(pid)).delete()
        for pid in participantes_ids - atuais:
            db.session.add(Participante(evento_id=evento_id, pessoa_id=int(pid)))

        db.session.commit()
        return redirect(url_for("ver_evento", evento_id=evento_id))

    selecionados = [str(p["pessoa_id"]) for p in participantes_do_evento(evento_id)]
    return render_template(
        "criar_evento.html", pessoas=pessoas_lista, evento=ev, selecionados=selecionados
    )


@app.route("/eventos/<int:evento_id>/excluir", methods=["POST"])
def excluir_evento(evento_id):
    ev = Evento.query.get(evento_id)
    if ev:
        db.session.delete(ev)
        db.session.commit()
    return redirect(url_for("home"))


# ---------------------------------------------------------------------------
# Rotas — Página do evento
# ---------------------------------------------------------------------------
@app.route("/eventos/<int:evento_id>")
def ver_evento(evento_id):
    ev = Evento.query.get(evento_id)
    if not ev:
        return redirect(url_for("home"))
    participantes = participantes_do_evento(evento_id)
    total = len(participantes)
    pagos = sum(1 for p in participantes if p["pago"])
    valor_por_pessoa = (ev.valor_total / total) if total else 0
    pct = round(100 * pagos / total) if total else 0
    link_evento = request.url_root.rstrip("/") + url_for("ver_evento", evento_id=evento_id)
    return render_template(
        "evento.html",
        ev=ev,
        participantes=participantes,
        total=total,
        pagos=pagos,
        valor_por_pessoa=valor_por_pessoa,
        pct=pct,
        link_evento=link_evento,
    )


@app.route("/eventos/<int:evento_id>/pagar/<int:pessoa_id>", methods=["POST"])
def marcar_pago(evento_id, pessoa_id):
    part = Participante.query.filter_by(evento_id=evento_id, pessoa_id=pessoa_id).first()
    if part:
        part.pago = True
        part.pago_em = datetime.now().strftime("%d/%m/%Y às %H:%M")
        db.session.commit()
    return redirect(url_for("ver_evento", evento_id=evento_id))


@app.route("/eventos/<int:evento_id>/pix/<int:pessoa_id>")
def pix_pessoa(evento_id, pessoa_id):
    ev = Evento.query.get(evento_id)
    if not ev:
        return redirect(url_for("home"))
    participantes = participantes_do_evento(evento_id)
    pessoa = next((p for p in participantes if p["pessoa_id"] == pessoa_id), None)
    if not pessoa:
        return redirect(url_for("ver_evento", evento_id=evento_id))

    total = len(participantes)
    valor = (ev.valor_total / total) if total else 0
    payload = gerar_payload_pix(ev.pix_chave, ev.pix_nome, ev.pix_cidade, valor, ev.nome[:20])
    qr_b64 = qrcode_base64(payload)
    link_evento = request.url_root.rstrip("/") + url_for("ver_evento", evento_id=evento_id)

    return render_template(
        "pix.html",
        ev=ev,
        pessoa=pessoa,
        valor=valor,
        payload=payload,
        qr_b64=qr_b64,
        link_evento=link_evento,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
