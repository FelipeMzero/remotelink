# RemoteLink 🔗

Alternativa ao AnyDesk em Python puro — acesso remoto via rede local por código de acesso, hostname ou IP.

---

## ✨ Funcionalidades

- **Código de Acesso Único** — Cada máquina tem um código XXX-XXX-XXX gerado a partir do hardware
- **Pré-visualização da Conexão** — Veja informações do alvo antes de conectar
- **3 modos de conexão:**
  - Por **Código de Acesso** (`ABC-DEF-GHI`)
  - Por **IP** (`192.168.1.50`)
  - Por **Hostname** (`SERVIDOR01`, `PC-JOAO`)
- **Descoberta Automática** — Escaneia a rede local em busca de máquinas
- **Servidor embutido** — Cada instância pode receber e enviar conexões
- **Interface moderna** com tema escuro

---

## 🚀 Instalação Rápida

### 1. Instalar dependências

```bash
pip install -r requirements.txt
```

**Dependências:**
| Pacote | Para quê |
|--------|----------|
| `Pillow` | Processar frames JPEG |
| `mss` | Captura de tela (host) |
| `pyautogui` | Controle de mouse/teclado (host) |

### 2. Rodar

```bash
python main.py
```

---

## 🏗 Converter para .EXE

```bash
pip install pyinstaller
python build.py
```

O arquivo `dist/RemoteLink.exe` será gerado (~40-80MB, standalone).

---

## 📁 Estrutura

```
remotelink/
├── main.py              ← Ponto de entrada
├── requirements.txt
├── build.py             ← Script PyInstaller
├── core/
│   ├── identity.py      ← Código de máquina + descoberta de rede
│   ├── server.py        ← Servidor (captura tela + recebe input)
│   └── client.py        ← Cliente (recebe frames + envia input)
└── gui/
    └── app.py           ← Interface Tkinter completa
```

---

## 🔌 Como Funciona

### Protocolo de Rede
- **Porta:** `52340` TCP
- Handshake JSON com validação de código de acesso
- Frames JPEG comprimidos em stream contínuo
- Eventos de input em JSON (mouse, teclado)

### Código de Acesso
- Gerado a partir de: MAC address + hostname + plataforma
- Estável por máquina (não muda ao reiniciar)
- Formato: `XXX-XXX-XXX` (sem caracteres ambíguos: 0, O, I, 1, L)

### Fluxo de Conexão
```
[Viewer] → TCP connect → [Host:52340]
[Viewer] → {version, access_code} JSON →
         ← {status: accepted, machine: {...}} ←
[Host]   → JPEG frames stream →
[Viewer] → input events (mouse/keyboard) →
```

---

## ⚙️ Requisitos

- Python 3.10+
- Windows / Linux / macOS
- Rede local (LAN) ou mesmo IP acessível

---

## 🔒 Segurança

- Conexões validadas por código de acesso
- O servidor só aceita 1 cliente por vez
- Sem relay externo — tudo na rede local
- Para segurança extra: use em VPN ou rede privada

---

## 🛠 Solução de Problemas

**"Connection refused"**
→ Certifique-se que o RemoteLink está rodando no PC alvo e o servidor foi iniciado

**Firewall bloqueando**
→ Libere a porta `52340` no Windows Defender / firewall

**Hostname não resolve**
→ Use o IP diretamente, ou certifique-se que o DNS local está configurado

**Tela não aparece**
→ Instale `mss` e `Pillow`: `pip install mss Pillow`
