#!/usr/bin/env python3
"""
Wi-Fi Senhas - lista as redes Wi-Fi salvas neste computador e suas senhas.
Permite exportar/importar listas, ver o status de cada rede (conectada agora,
salva neste PC ou só importada), conectar nas que ainda não existem no PC,
editar senha e deletar redes.

Funciona de verdade (conectar/editar/deletar) apenas no Windows.
No Linux/macOS, lista, exporta e importa normalmente, mas conectar/editar/
deletar ainda não foram implementados.

Use apenas no SEU computador / com autorização.
Não precisa instalar nada além do Python 3.8+ (tkinter já vem junto).
"""

import csv
import ctypes
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import xml.etree.ElementTree as ET
from tkinter import filedialog, messagebox, simpledialog, ttk
from xml.sax.saxutils import escape

SISTEMA = platform.system()


def executar(cmd):
    """Executa um comando e devolve o texto da saída (ou '' em caso de erro)."""
    kwargs = {}
    encoding = "utf-8"
    if SISTEMA == "Windows":
        try:
            encoding = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
        except Exception:
            encoding = "cp850"
        kwargs["creationflags"] = 0x08000000  # sem janela de console
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding=encoding, errors="replace", timeout=30, **kwargs
        )
        return r.stdout or ""
    except Exception:
        return ""


def eh_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


CORES_FORCA = {"Fraca": "#E62845", "Média": "#FFC900",
               "Forte": "#00B15A", "": "#666666"}


def forca_senha(senha):
    """Estimativa simples da força da senha ('Fraca'/'Média'/'Forte'), só para
    referência visual. '' quando não há senha (rede aberta)."""
    if not senha:
        return ""
    pontos = 0
    if len(senha) >= 8:
        pontos += 1
    if len(senha) >= 12:
        pontos += 1
    if re.search(r"[A-Z]", senha) and re.search(r"[a-z]", senha):
        pontos += 1
    if re.search(r"\d", senha):
        pontos += 1
    if re.search(r"[^A-Za-z0-9]", senha):
        pontos += 1
    if pontos <= 1:
        return "Fraca"
    if pontos <= 3:
        return "Média"
    return "Forte"


# ---------------------------- Windows: leitura ----------------------------
def redes_windows():
    """Método principal: exporta os perfis para XML (não depende do idioma).
    Devolve [(nome, senha, criptografia), ...]."""
    resultado = []
    try:
        with tempfile.TemporaryDirectory() as pasta:
            executar(f'netsh wlan export profile key=clear folder="{pasta}"')
            for arq in os.listdir(pasta):
                if not arq.lower().endswith(".xml"):
                    continue
                try:
                    raiz = ET.parse(os.path.join(pasta, arq)).getroot()
                except Exception:
                    continue
                nome, senha, auth, enc = "", "", "", ""
                for el in raiz.iter():
                    tag = el.tag.split("}")[-1]
                    if tag == "name" and not nome:
                        nome = (el.text or "").strip()
                    elif tag == "keyMaterial":
                        senha = (el.text or "").strip()
                    elif tag == "authentication" and not auth:
                        auth = (el.text or "").strip()
                    elif tag == "encryption" and not enc:
                        enc = (el.text or "").strip()
                if nome:
                    cripto = f"{auth}/{enc}" if auth or enc else ""
                    resultado.append((nome, senha, cripto))
    except Exception:
        pass
    if not resultado:  # plano B: ler o texto do netsh
        resultado = redes_windows_texto()
    return sorted(resultado, key=lambda x: x[0].lower())


def redes_windows_texto():
    saida = executar(["netsh", "wlan", "show", "profiles"])
    nomes = []
    for linha in saida.splitlines():
        if ":" in linha:
            nome = linha.split(":", 1)[1].strip()
            if nome and not nome.startswith("<"):
                nomes.append(nome)

    resultado = []
    for nome in nomes:
        det = executar(["netsh", "wlan", "show", "profile",
                       f"name={nome}", "key=clear"])
        senha, auth, enc = "", "", ""
        for linha in det.splitlines():
            if ":" not in linha:
                continue
            chave, valor = linha.split(":", 1)
            chave, valor = chave.strip(), valor.strip()
            if re.search(r"(key content|conte.do da chave|contenido de la clave)", chave, re.I):
                senha = valor
            elif re.search(r"(authentication|autentica)", chave, re.I) and not auth:
                auth = valor
            elif re.search(r"(cipher|cifra)", chave, re.I) and not enc:
                enc = valor
        cripto = f"{auth}/{enc}" if auth or enc else ""
        resultado.append((nome, senha, cripto))
    return resultado


# ----------------------------- Linux -----------------------------
def redes_linux():
    saida = executar(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    resultado = []
    for linha in saida.splitlines():
        nome, _, tipo = linha.rpartition(":")
        if tipo.strip() in ("802-11-wireless", "wifi"):
            nome = nome.replace("\\:", ":")
            senha = executar(
                ["nmcli", "-s", "-g", "802-11-wireless-security.psk",
                 "connection", "show", nome]
            ).strip()
            cripto = executar(
                ["nmcli", "-g", "802-11-wireless-security.key-mgmt",
                 "connection", "show", nome]
            ).strip()
            resultado.append((nome, senha, cripto))
    return resultado


# ----------------------------- macOS -----------------------------
def redes_macos():
    saida = executar(["networksetup", "-listpreferredwirelessnetworks", "en0"])
    resultado = []
    for linha in saida.splitlines()[1:]:
        nome = linha.strip()
        if not nome:
            continue
        senha = executar(
            ["security", "find-generic-password", "-wa", nome]).strip()
        # macOS não expõe o tipo facilmente
        resultado.append((nome, senha, ""))
    return resultado


def listar_redes():
    if SISTEMA == "Windows":
        return redes_windows()
    if SISTEMA == "Linux":
        return redes_linux()
    if SISTEMA == "Darwin":
        return redes_macos()
    return []


# --------------------------- Conexão atual (status) ---------------------------
def interface_wifi_windows():
    saida = executar(["netsh", "wlan", "show", "interfaces"])
    m = re.search(r"^\s*Name\s*:\s*(.+)$", saida, re.M)
    return m.group(1).strip() if m else None


def ssid_atual():
    """Devolve o nome da rede Wi-Fi conectada agora, ou None."""
    if SISTEMA == "Windows":
        saida = executar(["netsh", "wlan", "show", "interfaces"])
        m = re.search(r"^\s*SSID\s*:\s*(.+)$", saida, re.M)
        return m.group(1).strip() if m else None
    if SISTEMA == "Linux":
        saida = executar(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"])
        for linha in saida.splitlines():
            ativo, _, ssid = linha.partition(":")
            if ativo.strip().lower() == "yes":
                return ssid.strip()
        return None
    if SISTEMA == "Darwin":
        saida = executar(["networksetup", "-getairportnetwork", "en0"])
        m = re.search(r":\s*(.+)$", saida)
        return m.group(1).strip() if m else None
    return None


# --------------------------- Windows: criar/editar/apagar perfil ---------------------------
def perfil_xml(nome, senha):
    aberta = not senha
    if aberta:
        seguranca = """
      <authEncryption>
        <authentication>open</authentication>
        <encryption>none</encryption>
        <useOneX>false</useOneX>
      </authEncryption>"""
    else:
        seguranca = f"""
      <authEncryption>
        <authentication>WPA2PSK</authentication>
        <encryption>AES</encryption>
        <useOneX>false</useOneX>
      </authEncryption>
      <sharedKey>
        <keyType>passPhrase</keyType>
        <protected>false</protected>
        <keyMaterial>{escape(senha)}</keyMaterial>
      </sharedKey>"""
    nome_x = escape(nome)
    return f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>{nome_x}</name>
  <SSIDConfig>
    <SSID>
      <name>{nome_x}</name>
    </SSID>
  </SSIDConfig>
  <connectionType>ESS</connectionType>
  <connectionMode>auto</connectionMode>
  <MSM>
    <security>{seguranca}
    </security>
  </MSM>
</WLANProfile>"""


def adicionar_perfil_windows(nome, senha):
    """Cria (ou sobrescreve) o perfil da rede no Windows. Assume WPA2-PSK/AES
    quando há senha, ou rede aberta quando não há."""
    with tempfile.TemporaryDirectory() as pasta:
        caminho = os.path.join(pasta, "perfil.xml")
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(perfil_xml(nome, senha))
        saida = executar(
            f'netsh wlan add profile filename="{caminho}" user=all')
    return bool(re.search(r"(add|adicionad|añadid)", saida, re.I)) and not re.search(
        r"(error|erro|falh|cannot|não foi poss.vel)", saida, re.I
    )


def deletar_perfil_windows(nome, interface=None):
    cmd = f'netsh wlan delete profile name="{nome}"'
    if interface:
        cmd += f' interface="{interface}"'
    saida = executar(cmd)
    return not re.search(r"(error|erro|n.o foi encontrad|not found)", saida, re.I)


def editar_senha_windows(nome, nova_senha, interface=None):
    deletar_perfil_windows(nome, interface)
    return adicionar_perfil_windows(nome, nova_senha)


def conectar_rede_windows(nome, interface, aguardar=8):
    cmd = f'netsh wlan connect name="{nome}"'
    if interface:
        cmd += f' interface="{interface}"'
    saida = executar(cmd)
    if re.search(r"(não foi possível|cannot|failed|erro|error)", saida, re.I):
        return False, saida.strip() or "falhou ao iniciar a conexão"
    fim = time.time() + aguardar
    while time.time() < fim:
        time.sleep(1)
        if ssid_atual() == nome:
            return True, "conectado"
    return False, "não conectou dentro do tempo (fora de alcance?)"


def conectar_novas(redes_importadas, progresso_cb, parar_cb):
    """Cria o perfil (se precisar) e conecta só nas redes importadas que ainda
    não existem salvas neste computador."""
    if SISTEMA != "Windows":
        progresso_cb(
            None, "Esse recurso, por enquanto, só foi implementado para Windows.")
        return
    interface = interface_wifi_windows()
    for r in redes_importadas:
        if parar_cb():
            progresso_cb(None, "Interrompido pelo usuário.")
            return
        nome, senha = r["nome"], r["senha"]
        progresso_cb(nome, "criando perfil...")
        if not adicionar_perfil_windows(nome, senha):
            progresso_cb(nome, "❌ não foi possível criar o perfil")
            continue
        progresso_cb(nome, "conectando...")
        ok, msg = conectar_rede_windows(nome, interface)
        progresso_cb(nome, "✅ conectado" if ok else f"❌ {msg}")
        if ok:
            r["origem"] = "dispositivo"
    progresso_cb(None, "Concluído.")


# ----------------------------- Exportar / Importar -----------------------------
def exportar_arquivo(redes, caminho):
    """redes: lista de (nome, senha, cripto)."""
    ext = caminho.lower().rsplit(".", 1)[-1]
    if ext == "csv":
        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Rede", "Senha", "Criptografia"])
            w.writerows(redes)
    elif ext == "json":
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(
                [{"rede": n, "senha": s, "criptografia": c}
                    for n, s, c in redes],
                f, ensure_ascii=False, indent=2,
            )
    else:
        with open(caminho, "w", encoding="utf-8") as f:
            for n, s, c in redes:
                f.write(
                    f"Rede: {n}\nSenha: {s or '(sem senha / aberta)'}\n"
                    f"Criptografia: {c or '(desconhecida)'}\n\n"
                )


def ler_importacao(caminho):
    """Lê um arquivo exportado (csv/json/txt) e devolve [(nome, senha, cripto), ...]."""
    ext = caminho.lower().rsplit(".", 1)[-1]
    resultado = []
    if ext == "csv":
        with open(caminho, encoding="utf-8-sig") as f:
            linhas = list(csv.reader(f))
        inicio = 0
        if linhas and linhas[0] and linhas[0][0].strip().lower() in ("rede", "ssid", "nome", "name"):
            inicio = 1
        for linha in linhas[inicio:]:
            if len(linha) >= 2:
                cripto = linha[2].strip() if len(linha) >= 3 else ""
                resultado.append((linha[0].strip(), linha[1].strip(), cripto))
    elif ext == "json":
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
        for item in dados:
            nome = str(item.get("rede") or item.get("nome")
                       or item.get("ssid") or "").strip()
            senha = str(item.get("senha") or item.get(
                "password") or "").strip()
            cripto = str(item.get("criptografia")
                         or item.get("cripto") or "").strip()
            if nome:
                resultado.append((nome, senha, cripto))
    else:  # txt
        nome_atual, senha_atual = None, ""
        with open(caminho, encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if linha.lower().startswith("rede:"):
                    nome_atual = linha.split(":", 1)[1].strip()
                    senha_atual = ""
                elif linha.lower().startswith("senha:") and nome_atual:
                    senha_atual = linha.split(":", 1)[1].strip()
                    if senha_atual.startswith("("):
                        senha_atual = ""
                elif linha.lower().startswith("criptografia:") and nome_atual:
                    cripto = linha.split(":", 1)[1].strip()
                    if cripto.startswith("("):
                        cripto = ""
                    resultado.append((nome_atual, senha_atual, cripto))
                    nome_atual = None
        if nome_atual:  # arquivo sem a linha "Criptografia"
            resultado.append((nome_atual, senha_atual, ""))
    return [r for r in resultado if r[0]]


# ------------------------------- App -------------------------------
COLUNAS = ("ssid", "senha", "cripto", "status", "forca")
TITULOS = {
    "ssid": "SSID", "senha": "Senha", "cripto": "Criptografia",
    "status": "Status", "forca": "Nível (força)",
}
LARGURAS = {"ssid": 220, "senha": 170,
            "cripto": 140, "status": 170, "forca": 120}


CORES_ZEBRA = {"par": "#ffffff", "impar": "#f2f4f7"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Wi-Fi-Senhas")
        self.geometry("860x560")
        self.minsize(680, 400)
        self.redes = []            # lista de dicts: nome, senha, cripto, origem
        self.nomes_dispositivo = set()
        self.ordenar_coluna = None
        self.ordenar_reverso = False
        # iid -> tk.Label (texto colorido da coluna "Nível")
        self._overlays_forca = {}

        self._estilo()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        aba_inicio = ttk.Frame(self.notebook)
        aba_sobre = ttk.Frame(self.notebook)
        aba_apoie = ttk.Frame(self.notebook)
        self.notebook.add(aba_inicio, text="🏠  Início")
        self.notebook.add(aba_sobre, text="ℹ️  Sobre")
        self.notebook.add(aba_apoie, text="💜  Apoie")

        self._construir_aba_inicio(aba_inicio)
        self._construir_aba_sobre(aba_sobre)
        self._construir_aba_apoie(aba_apoie)
        self.notebook.bind("<<NotebookTabChanged>>",
                           lambda e: self.after(1, self._posicionar_overlays))

        menubar = tk.Menu(self)
        menu_ajuda = tk.Menu(menubar, tearoff=0)
        menu_ajuda.add_command(
            label="Sobre", command=lambda: self.notebook.select(aba_sobre))
        menu_ajuda.add_command(
            label="Apoie", command=lambda: self.notebook.select(aba_apoie))
        menubar.add_cascade(label="Ajuda", menu=menu_ajuda)
        self.config(menu=menubar)

        self.after(100, self.carregar)

    # ----------------------------- Aba Início -----------------------------
    def _construir_aba_inicio(self, aba):
        topo1 = ttk.Frame(aba, padding=(10, 10, 10, 4))
        topo1.pack(fill="x")
        ttk.Button(topo1, text="🔄  Atualizar", style="Big.TButton",
                   command=self.carregar).pack(side="left")
        ttk.Button(topo1, text="📥  Importar...", style="Big.TButton",
                   command=self.importar).pack(side="left", padx=6)
        ttk.Button(topo1, text="📤  Exportar...", style="Big.TButton",
                   command=self.exportar).pack(side="left")
        if SISTEMA == "Windows" and not eh_admin():
            ttk.Button(topo1, text="🛡️  Executar como admin", style="Big.TButton",
                       command=self.pedir_admin).pack(side="right")

        topo2 = ttk.Frame(aba, padding=(10, 4, 10, 8))
        topo2.pack(fill="x")
        ttk.Button(topo2, text="📶  Conectar nas novas", style="Big.TButton",
                   command=self.conectar_novas).pack(side="left")
        ttk.Button(topo2, text="✏️  Editar senha", style="Big.TButton",
                   command=self.editar_senha).pack(side="left", padx=6)
        ttk.Button(topo2, text="🗑️  Deletar", style="Big.TButton",
                   command=self.deletar).pack(side="left")
        self.mostrar = tk.BooleanVar(value=True)
        ttk.Checkbutton(topo2, text="Mostrar senhas", variable=self.mostrar,
                        command=self.preencher).pack(side="right")

        self.barra_carregando = ttk.Progressbar(aba, mode="indeterminate")
        # só é exibida (pack) enquanto uma operação está em andamento

        area_tabela = ttk.Frame(aba)
        area_tabela.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        self.tabela = ttk.Treeview(
            area_tabela, columns=COLUNAS, show="headings", style="Big.Treeview"
        )
        for col in COLUNAS:
            self.tabela.heading(col, text=TITULOS[col],
                                command=lambda c=col: self.ordenar_por(c))
            self.tabela.column(col, width=LARGURAS[col], anchor="w")

        barra_v = ttk.Scrollbar(
            area_tabela, orient="vertical", command=self._on_yscroll)
        barra_h = ttk.Scrollbar(
            area_tabela, orient="horizontal", command=self._on_xscroll)
        self.tabela.configure(yscrollcommand=barra_v.set,
                              xscrollcommand=barra_h.set)

        self.tabela.grid(row=0, column=0, sticky="nsew")
        barra_v.grid(row=0, column=1, sticky="ns")
        barra_h.grid(row=1, column=0, sticky="ew")
        area_tabela.rowconfigure(0, weight=1)
        area_tabela.columnconfigure(0, weight=1)

        self.tabela.bind("<Double-1>", self.copiar_senha)
        self.tabela.bind("<MouseWheel>", lambda e: self.after(
            1, self._posicionar_overlays))
        self.tabela.bind("<Button-4>", lambda e: self.after(1,
                         self._posicionar_overlays))
        self.tabela.bind("<Button-5>", lambda e: self.after(1,
                         self._posicionar_overlays))
        self.tabela.bind("<ButtonRelease-1>",
                         lambda e: self.after(1, self._posicionar_overlays))
        self.tabela.bind("<Configure>", lambda e: self._posicionar_overlays())

        # linhas zebradas (fundo), texto preto padrão — a cor só aparece
        # na coluna "Nível", via rótulos sobrepostos (ver _posicionar_overlays)
        for zebra_tag, bg in CORES_ZEBRA.items():
            self.tabela.tag_configure(
                zebra_tag, foreground="#000000", background=bg)

        rodape = ttk.Frame(aba)
        rodape.pack(fill="x")
        self.status = ttk.Label(rodape, text="", padding=10)
        self.status.pack(side="left")

    def _on_yscroll(self, *args):
        self.tabela.yview(*args)
        self._posicionar_overlays()

    def _on_xscroll(self, *args):
        self.tabela.xview(*args)
        self._posicionar_overlays()

    # ----------------------------- Aba Sobre -----------------------------
    NOME_APP = "Wi-Fi-Senhas"
    VERSAO_APP = "1.0"
    AUTOR = "Ivande Coelho"
    SISTEMAS_APP = "Windows, Linux, macOS"
    LINK_GITHUB = "https://github.com/IvandeCoelho/Wi-Fi-Senhas"
    DESCRICAO_APP = (
        "Wi-Fi Senhas - lista as redes Wi-Fi salvas neste computador e suas senhas.\n"
        "Permite exportar/importar listas, ver o status de cada rede (conectada agora,\n"
        "salva neste PC ou só importada), conectar nas que ainda não existem no PC,\n"
        "editar senha e deletar redes.\n"
        " \n"
        "Funciona de verdade (conectar/editar/deletar) apenas no Windows.\n"
        "No Linux/macOS, lista, exporta e importa normalmente, mas conectar/editar/\n"
        "deletar ainda não foram implementados.\n"
        " \n"
        "Use apenas no SEU computador / com autorização.\n"
        "Não precisa instalar nada além do Python 3.8+ (tkinter já vem junto)."
    )

    def _construir_aba_sobre(self, aba):
        area = ttk.Frame(aba)
        area.pack(fill="both", expand=True, padx=24, pady=20)

        ttk.Label(area, text=self.NOME_APP, font=(
            "Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(
            area, text="Lista, exporta e gerencia as redes Wi-Fi salvas no computador.",
            font=("Segoe UI", 10), foreground=self.COR_TEXTO_SEC,
        ).pack(anchor="w", pady=(2, 16))

        campos = ttk.Frame(area)
        campos.pack(anchor="w", fill="x")

        def campo(linha, rotulo, construtor_valor):
            ttk.Label(campos, text=rotulo, font=("Segoe UI", 10, "bold")).grid(
                row=linha, column=0, sticky="nw", padx=(0, 10), pady=4
            )
            construtor_valor(linha)

        def valor_texto(txt):
            return lambda linha: ttk.Label(campos, text=txt, font=("Segoe UI", 10)).grid(
                row=linha, column=1, sticky="w", pady=4
            )

        campo(0, "Versão:", valor_texto(self.VERSAO_APP))
        campo(1, "Autor:", valor_texto(self.AUTOR))
        campo(2, "Sistema:", valor_texto(self.SISTEMAS_APP))

        def valor_link(linha):
            lbl = tk.Label(
                campos, text=self.LINK_GITHUB, font=(
                    "Segoe UI", 10, "underline"),
                fg=self.COR_LINK, bg=self.COR_FUNDO, cursor="hand2",
            )
            lbl.grid(row=linha, column=1, sticky="w", pady=4)
            lbl.bind("<Button-1>", lambda e: self.abrir_github())

        campo(3, "Repositório:", valor_link)

        ttk.Label(area, text="Descrição", font=("Segoe UI", 11, "bold")).pack(
            anchor="w", pady=(20, 6)
        )
        ttk.Label(
            area, text=self.DESCRICAO_APP, font=("Segoe UI", 9),
            foreground=self.COR_TEXTO_SEC, justify="left",
        ).pack(anchor="w")

    # ----------------------------- Aba Apoie -----------------------------
    CHAVE_PIX = "ivandealveslp@gmail.com"

    def _construir_aba_apoie(self, aba):
        area = ttk.Frame(aba)
        area.pack(fill="both", expand=True)
        canvas = tk.Canvas(area, background=self.cget(
            "background"), highlightthickness=0)
        barra = ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
        corpo = ttk.Frame(canvas)
        corpo.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=corpo, anchor="nw")
        canvas.configure(yscrollcommand=barra.set)
        canvas.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(
            int(-e.delta / 120), "units"))
        canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

        pad = {"padx": 24}
        largura_texto = 760

        def paragrafo(txt, **kw):
            ttk.Label(corpo, text=txt, wraplength=largura_texto, justify="left", **kw).pack(
                anchor="w", **pad, pady=(0, 10)
            )

        ttk.Label(corpo, text="💝 Curtiu o projeto? Apoie!",
                  font=("Segoe UI", 18, "bold")).pack(anchor="w", **pad, pady=(20, 6))
        paragrafo(
            "Feito com dedicação para facilitar a vida de quem trabalha com tecnologia e educação.",
            font=("Segoe UI", 10), foreground="#555555",
        )
        ttk.Label(corpo, text="🤝 Menos dores de cabeça, mais tempo para o que importa!",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", **pad, pady=(10, 6))
        paragrafo(
            "Caso essa solução tenha ajudado você e economizado algumas dores de cabeça, "
            "que tal dar uma força para manter o projeto vivo? 😄",
            font=("Segoe UI", 10),
        )
        paragrafo(
            "O aplicativo é desenvolvido de forma independente e voluntária. Sua "
            "contribuição é opcional e ajuda a incentivar melhorias, correções e novas "
            "funcionalidades.",
            font=("Segoe UI", 10),
        )
        paragrafo(
            "Não pode contribuir financeiramente? Sem problemas! ⭐ Deixar uma estrela no "
            "GitHub, compartilhar o projeto ou enviar sugestões também ajuda muito!",
            font=("Segoe UI", 10),
        )
        ttk.Label(corpo, text="☕ Quer pagar um cafezinho ao desenvolvedor?",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", **pad, pady=(10, 10))

        caixa = ttk.Frame(corpo, style="Card.TFrame", padding=16)
        caixa.pack(anchor="w", padx=24, pady=(0, 16), fill="x")
        ttk.Label(caixa, text="Chave PIX (e-mail):", style="Card.TLabel",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.var_pix = tk.StringVar(value=self.CHAVE_PIX)
        entrada = ttk.Entry(caixa, textvariable=self.var_pix,
                            font=("Consolas", 11), state="readonly")
        entrada.pack(anchor="w", fill="x", pady=(6, 10))
        botoes = ttk.Frame(caixa)
        botoes.pack(anchor="w")
        ttk.Button(botoes, text="📋  Copiar chave PIX", style="Pix.TButton",
                   command=self.copiar_pix).pack(side="left")
        ttk.Button(botoes, text="⭐  Apoiar no GitHub", style="Big.TButton",
                   command=self.abrir_github).pack(side="left", padx=(8, 0))

        rodape = ttk.Frame(corpo)
        rodape.pack(anchor="w", **pad, pady=(4, 4))
        for txt in ("🔓 Código aberto", "♡ Apoio voluntário", "🚫 Sem obrigação de contribuir"):
            ttk.Label(rodape, text=txt, font=("Segoe UI", 9), foreground="#777777").pack(
                side="left", padx=(0, 16)
            )
        ttk.Label(corpo, text="Obrigado por usar o projeto e fazer parte dessa ideia! 🖤",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", **pad, pady=(6, 20))

    def copiar_pix(self):
        self.clipboard_clear()
        self.clipboard_append(self.CHAVE_PIX)
        messagebox.showinfo(
            "Chave PIX", "Chave PIX copiada para a área de transferência!")

    def abrir_github(self):
        if not self.LINK_GITHUB:
            messagebox.showinfo(
                "Apoiar no GitHub",
                "[PLACEHOLDER] Defina o link do repositório na constante LINK_GITHUB, no código.",
            )
            return
        import webbrowser
        webbrowser.open(self.LINK_GITHUB)

    # Paleta no estilo do EasyBlock: fundo cinza-claro, cartões brancos,
    # abas achatadas com a ativa em branco.
    COR_FUNDO = "#eef0f2"
    COR_CARTAO = "#ffffff"
    COR_BORDA = "#d7dadf"
    COR_TEXTO = "#1a1a1a"
    COR_TEXTO_SEC = "#5f6368"
    COR_ABA = "#e3e6ea"
    COR_ABA_ATIVA = "#ffffff"
    COR_LINK = "#1a5fb4"

    def _estilo(self):
        self.configure(background=self.COR_FUNDO)
        estilo = ttk.Style(self)
        try:
            estilo.theme_use("clam")
        except Exception:
            pass

        estilo.configure(".", background=self.COR_FUNDO, foreground=self.COR_TEXTO,
                         font=("Segoe UI", 10))
        estilo.configure("TFrame", background=self.COR_FUNDO)
        estilo.configure("TLabel", background=self.COR_FUNDO,
                         foreground=self.COR_TEXTO)
        estilo.configure(
            "TCheckbutton", background=self.COR_FUNDO, foreground=self.COR_TEXTO)
        estilo.configure("TEntry", fieldbackground=self.COR_CARTAO,
                         bordercolor=self.COR_BORDA)

        # Botões: fundo claro, bordinha, estilo "cartão" como no EasyBlock
        estilo.configure(
            "Big.TButton", font=("Segoe UI", 11), padding=(12, 8),
            background=self.COR_CARTAO, foreground=self.COR_TEXTO,
            bordercolor=self.COR_BORDA, relief="solid", borderwidth=1,
        )
        estilo.map(
            "Big.TButton",
            background=[("active", "#f5f6f8"), ("pressed", "#e9ebee")],
        )

        estilo.configure("Big.Treeview", font=("Segoe UI", 10), rowheight=30,
                         background=self.COR_CARTAO, fieldbackground=self.COR_CARTAO)
        estilo.configure("Big.Treeview.Heading", font=("Segoe UI", 10, "bold"),
                         background=self.COR_ABA, foreground=self.COR_TEXTO)

        # Abas: achatadas, maiores que o padrão mas menores que os botões (fonte 11),
        # a aba ativa fica branca (como um "cartão" em primeiro plano), igual ao EasyBlock.
        estilo.configure("TNotebook", background=self.COR_FUNDO,
                         borderwidth=0, tabmargins=(4, 4, 4, 0))
        estilo.configure(
            "TNotebook.Tab", font=("Segoe UI", 10), padding=(16, 8),
            background=self.COR_ABA, foreground=self.COR_TEXTO_SEC, borderwidth=0,
        )
        estilo.map(
            "TNotebook.Tab",
            background=[("selected", self.COR_ABA_ATIVA)],
            foreground=[("selected", self.COR_TEXTO)],
        )

        estilo.configure("Pix.TButton", font=("Segoe UI", 10, "bold"),
                         padding=(12, 8), background="#FFC900", bordercolor="#FFC900")
        estilo.map("Pix.TButton", background=[("active", "#e6b500")])

        # "Cartão" branco com borda, usado na caixa da chave PIX
        estilo.configure("Card.TFrame", background=self.COR_CARTAO,
                         bordercolor=self.COR_BORDA, relief="solid", borderwidth=1)
        estilo.configure(
            "Card.TLabel", background=self.COR_CARTAO, foreground=self.COR_TEXTO)

    # ----------------------------- Carregando (progresso) -----------------------------
    def _iniciar_carregando(self):
        self.barra_carregando.pack(fill="x", padx=10, pady=(0, 4))
        self.barra_carregando.start(12)

    def _parar_carregando(self):
        self.barra_carregando.stop()
        self.barra_carregando.pack_forget()

    # ----------------------------- Carregar / preencher -----------------------------
    def carregar(self):
        self.status.config(text="Lendo redes...")
        self._iniciar_carregando()
        self.update_idletasks()
        dispositivo = listar_redes()
        self.redes = [
            {"nome": n, "senha": s, "cripto": c, "origem": "dispositivo"}
            for n, s, c in dispositivo
        ]
        self.nomes_dispositivo = {r["nome"] for r in self.redes}
        self.preencher()
        self._parar_carregando()
        if not self.redes:
            self.status.config(
                text="Nenhuma rede encontrada (no Linux/macOS pode precisar de permissão de administrador)."
            )
        else:
            msg = f"{len(self.redes)} rede(s) neste PC. Dois cliques numa linha copiam a senha."
            if SISTEMA == "Windows" and not eh_admin():
                msg += " (Sem administrador: algumas senhas podem aparecer vazias.)"
            self.status.config(text=msg)

    def ordenar_por(self, coluna):
        if self.ordenar_coluna == coluna:
            self.ordenar_reverso = not self.ordenar_reverso
        else:
            self.ordenar_coluna = coluna
            self.ordenar_reverso = False

        chaves = {
            "ssid": lambda r: r["nome"].lower(),
            "senha": lambda r: r["senha"].lower(),
            "cripto": lambda r: r["cripto"].lower(),
            "status": lambda r: r["origem"],
            "forca": lambda r: len(r["senha"] or ""),
        }
        self.redes.sort(key=chaves[coluna], reverse=self.ordenar_reverso)
        self.preencher()
        # seta visual (▲/▼) no cabeçalho da coluna ativa
        for col in COLUNAS:
            titulo = TITULOS[col]
            if col == coluna:
                titulo += " ▼" if self.ordenar_reverso else " ▲"
            self.tabela.heading(col, text=titulo)

    def preencher(self):
        for lbl in self._overlays_forca.values():
            lbl.destroy()
        self._overlays_forca = {}

        self.tabela.delete(*self.tabela.get_children())
        atual = ssid_atual()
        self._forca_dados = {}  # iid -> (texto, cor, cor_fundo)
        for i, r in enumerate(self.redes):
            nome, senha, cripto, origem = r["nome"], r["senha"], r["cripto"], r["origem"]
            if atual and nome == atual:
                status_txt = "🟢 Conectado agora"
            elif origem == "dispositivo":
                status_txt = "💾 Salva neste PC"
            else:
                status_txt = "📥 Importada (ainda não)"

            senha_txt = "(sem senha / aberta)" if not senha else (
                senha if self.mostrar.get() else "•" * 8)
            cripto_txt = cripto or "—"
            nivel = forca_senha(senha)
            forca_txt = nivel or "—"
            zebra = "par" if i % 2 == 0 else "impar"

            self.tabela.insert(
                "", "end", iid=nome,
                values=(nome, senha_txt, cripto_txt, status_txt, forca_txt),
                tags=(zebra,),
            )
            self._forca_dados[nome] = (forca_txt, CORES_FORCA.get(
                nivel, "#000000"), CORES_ZEBRA[zebra])

        self.after_idle(self._posicionar_overlays)

    def _posicionar_overlays(self):
        """Desenha um rótulo colorido por cima da célula da coluna 'Nível',
        já que o Treeview só permite colorir a linha inteira, não uma célula."""
        if not hasattr(self, "_forca_dados"):
            return
        visiveis = set(self.tabela.get_children())
        for iid in list(self._overlays_forca):
            if iid not in visiveis:
                self._overlays_forca.pop(iid).destroy()
        for iid in visiveis:
            bbox = self.tabela.bbox(iid, column="forca")
            lbl = self._overlays_forca.get(iid)
            if not bbox:
                if lbl:
                    lbl.place_forget()
                continue
            x, y, w, h = bbox
            texto, cor, fundo = self._forca_dados.get(
                iid, ("—", "#000000", "#ffffff"))
            if lbl is None:
                lbl = tk.Label(self.tabela, font=("Segoe UI", 10), anchor="w")
                self._overlays_forca[iid] = lbl
            lbl.configure(text=f"  {texto}", fg=cor, bg=fundo)
            lbl.place(x=x, y=y, width=w, height=h)

    def _rede_selecionada(self):
        sel = self.tabela.selection()
        if not sel:
            messagebox.showinfo(
                "Seleção", "Selecione uma rede na lista primeiro.")
            return None
        nome = sel[0]
        return next((r for r in self.redes if r["nome"] == nome), None)

    def copiar_senha(self, _evento):
        r = self._rede_selecionada()
        if not r:
            return
        if r["senha"]:
            self.clipboard_clear()
            self.clipboard_append(r["senha"])
            self.status.config(text=f"Senha de “{r['nome']}” copiada.")

    # ----------------------------- Exportar -----------------------------
    def exportar(self):
        if not self.redes:
            messagebox.showinfo("Exportar", "Não há redes para exportar.")
            return
        caminho = filedialog.asksaveasfilename(
            title="Exportar redes",
            defaultextension=".csv",
            initialfile="wifi_redes",
            filetypes=[("CSV (Excel)", "*.csv"),
                       ("JSON", "*.json"), ("Texto", "*.txt")],
        )
        if not caminho:
            return
        try:
            exportar_arquivo(
                [(r["nome"], r["senha"], r["cripto"])
                 for r in self.redes], caminho
            )
            messagebox.showwarning(
                "Exportado",
                f"Arquivo salvo em:\n{caminho}\n\nAtenção: ele contém senhas em texto puro. "
                "Guarde em local seguro e apague quando não precisar mais.",
            )
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível salvar:\n{e}")

    # ----------------------------- Importar -----------------------------
    def importar(self):
        caminho = filedialog.askopenfilename(
            title="Importar lista de redes",
            filetypes=[("Arquivos suportados", "*.csv *.json *.txt"),
                       ("CSV", "*.csv"), ("JSON", "*.json"), ("Texto", "*.txt")],
        )
        if not caminho:
            return
        try:
            importados = ler_importacao(caminho)
        except Exception as e:
            messagebox.showerror(
                "Erro", f"Não foi possível ler o arquivo:\n{e}")
            return
        novos, atualizados = 0, 0
        for nome, senha, cripto in importados:
            existente = next(
                (r for r in self.redes if r["nome"] == nome), None)
            if existente:
                if senha:
                    existente["senha"] = senha
                if cripto:
                    existente["cripto"] = cripto
                atualizados += 1
            else:
                self.redes.append(
                    {"nome": nome, "senha": senha,
                        "cripto": cripto, "origem": "importada"}
                )
                novos += 1
        self.preencher()
        messagebox.showinfo(
            "Importar",
            f"{novos} rede(s) nova(s) adicionada(s) à lista.\n"
            f"{atualizados} já existiam neste PC e tiveram os dados atualizados na lista.",
        )

    # ----------------------------- Conectar nas novas -----------------------------
    def conectar_novas(self):
        alvo = [r for r in self.redes if r["origem"] == "importada"]
        if not alvo:
            messagebox.showinfo(
                "Conectar", "Não há redes importadas pendentes — todas já existem neste PC."
            )
            return
        if SISTEMA != "Windows":
            messagebox.showinfo(
                "Conectar", "Esse recurso, por enquanto, só foi implementado para Windows.")
            return
        resp = messagebox.askyesno(
            "Conectar nas novas",
            f"Isso vai criar o perfil e tentar conectar, uma de cada vez, em {len(alvo)} "
            "rede(s) importada(s) que ainda não existem neste PC.\n\n"
            "As redes que já estavam salvas aqui não serão tocadas. Sua conexão atual pode "
            "cair durante o processo, e só funciona com redes que estiverem ao alcance agora.\n\n"
            "Continuar?",
        )
        if not resp:
            return

        janela = tk.Toplevel(self)
        janela.title("Conectando...")
        janela.geometry("460x360")

        ttk.Label(janela, text=f"Conectando em {len(alvo)} rede(s)...", padding=(
            10, 10, 10, 0)).pack(fill="x")
        barra = ttk.Progressbar(
            janela, mode="determinate", maximum=len(alvo), value=0)
        barra.pack(fill="x", padx=10, pady=(4, 8))

        area_log = ttk.Frame(janela)
        area_log.pack(fill="both", expand=True, padx=10)
        texto = tk.Text(area_log, state="disabled",
                        wrap="word", font=("Segoe UI", 10))
        barra_log = ttk.Scrollbar(
            area_log, orient="vertical", command=texto.yview)
        texto.configure(yscrollcommand=barra_log.set)
        texto.pack(side="left", fill="both", expand=True)
        barra_log.pack(side="right", fill="y")

        parar = {"sinal": False}

        def log(linha):
            texto.configure(state="normal")
            texto.insert("end", linha + "\n")
            texto.see("end")
            texto.configure(state="disabled")

        def progresso_cb(nome, status):
            def ui():
                log(status if nome is None else f"{nome}: {status}")
                if nome is not None and (status.startswith("✅") or status.startswith("❌")):
                    barra["value"] += 1
            self.after(0, ui)

        def parar_cb():
            return parar["sinal"]

        def finalizar():
            self.after(0, self.preencher)

        def ao_fechar():
            parar["sinal"] = True
            janela.destroy()

        janela.protocol("WM_DELETE_WINDOW", ao_fechar)
        ttk.Button(janela, text="Parar", style="Big.TButton",
                   command=lambda: parar.update(sinal=True)).pack(pady=10)

        def tarefa():
            conectar_novas(alvo, progresso_cb, parar_cb)
            finalizar()

        threading.Thread(target=tarefa, daemon=True).start()

    # ----------------------------- Editar senha -----------------------------
    def editar_senha(self):
        r = self._rede_selecionada()
        if not r:
            return
        nova = simpledialog.askstring(
            "Editar senha",
            f"Nova senha para “{r['nome']}”:\n(deixe em branco para rede aberta)",
            initialvalue=r["senha"],
        )
        if nova is None:
            return
        if r["origem"] == "dispositivo":
            if SISTEMA == "Windows":
                self.status.config(
                    text=f"Atualizando senha de “{r['nome']}”...")
                self._iniciar_carregando()
                self.update_idletasks()
                ok = editar_senha_windows(
                    r["nome"], nova, interface_wifi_windows())
                self._parar_carregando()
                if not ok:
                    messagebox.showerror(
                        "Erro",
                        "Não foi possível atualizar a senha no Windows "
                        "(a rede foi recriada assumindo WPA2-PSK/AES).",
                    )
                    return
                r["cripto"] = "WPA2PSK/AES" if nova else "open/none"
            else:
                messagebox.showwarning(
                    "Aviso",
                    "Editar a senha de verdade no sistema só foi implementado para Windows. "
                    "Vou atualizar apenas aqui na lista.",
                )
        r["senha"] = nova
        self.preencher()
        self.status.config(text=f"Senha de “{r['nome']}” atualizada.")

    # ----------------------------- Deletar -----------------------------
    def deletar(self):
        r = self._rede_selecionada()
        if not r:
            return
        apaga_de_verdade = r["origem"] == "dispositivo" and SISTEMA == "Windows"
        aviso = (
            "Isso vai apagar a rede salva de verdade no Windows."
            if apaga_de_verdade
            else "Ela só existe nesta lista (ainda não foi criada/salva neste PC)."
        )
        if not messagebox.askyesno("Deletar", f"Remover “{r['nome']}”?\n\n{aviso}"):
            return
        if apaga_de_verdade:
            deletar_perfil_windows(r["nome"], interface_wifi_windows())
        self.redes = [x for x in self.redes if x["nome"] != r["nome"]]
        self.preencher()
        self.status.config(text=f"“{r['nome']}” removida.")

    # ----------------------------- Admin -----------------------------
    def pedir_admin(self):
        resp = messagebox.askyesno(
            "Executar como administrador",
            "Vai abrir uma nova janela deste app com permissão de administrador "
            "(o Windows vai pedir sua confirmação) e fechar esta aqui.\n\nContinuar?",
        )
        if not resp:
            return
        if reabrir_como_admin():
            self.destroy()
        else:
            messagebox.showwarning(
                "Aviso", "Não foi possível reabrir como administrador. Tente clicar com o "
                "botão direito no arquivo e escolher “Executar como administrador”.",
            )


def reabrir_como_admin():
    """Reabre este script em um novo processo elevado (pede UAC)."""
    try:
        r = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable,
            f'"{os.path.abspath(__file__)}"', None, 1)
        return r > 32
    except Exception:
        return False


if __name__ == "__main__":
    try:
        App().mainloop()
    except Exception:
        # Mostra o erro numa janela, em vez de fechar sem avisar nada
        import traceback
        erro = traceback.format_exc()
        try:
            messagebox.showerror("Wi-Fi Senhas - erro ao iniciar", erro)
        except Exception:
            print(erro)
        input("Pressione Enter para sair...")
