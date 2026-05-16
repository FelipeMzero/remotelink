# RemoteLink

Alternativa ao AnyDesk em Python puro — acesso remoto via rede local por codigo de acesso, hostname ou IP. Leve, portatil e sem dependencias externas de servidor.

---

## Recursos

- **Codigo de Acesso Unico** — Cada maquina tem um codigo numerico `XXX-XXX` gerado a partir do hardware (MAC + hostname)
- **Pre-visualizacao** — Veja sistema, IP e hostname do alvo antes de conectar
- **3 modos de conexao:**
  - Codigo de Acesso (`123-456`)
  - IP direto (`192.168.1.50`)
  - Hostname (`SERVIDOR01`)
- **Descoberta Automatica** — Escaneia a rede local e lista maquinas com RemoteLink
- **Servidor duplo embutido** — Cada instancia pode ser host e viewer simultaneamente
- **Interface escura profissional** — Tema dark inspirado no GitHub
- **Standalone .EXE** — Gere um executavel unico com PyInstaller (sem precisar de Python no alvo)

---

## Indice

- [Instalacao](#instalacao)
- [Como usar](#como-usar)
- [Build .EXE](#build-exe)
- [Arquitetura](#arquitetura)
- [Protocolo](#protocolo)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Seguranca](#seguranca)
- [Solucao de problemas](#solucao-de-problemas)

---

## Instalacao

### Requisitos

- Python 3.10+
- Windows / Linux / macOS
- Rede local (LAN) ou IP acessivel

### Dependencias

```bash
pip install -r requirements.txt
```

| Pacote | Versao | Funcao |
|--------|--------|--------|
| `Pillow` | >= 10.0 | Codificacao JPEG dos frames |
| `mss` | >= 9.0 | Captura de tela (lado host) |
| `pynput` | >= 1.7 | Controle remoto de mouse/teclado |
| `pyautogui` | >= 0.9 | Automacao de input (fallback) |

### Executar

```bash
python main.py
```

A interface abre automaticamente. O servidor inicia em segundo plano apos alguns segundos.

---

## Como usar

### Conectar

1. Abra o RemoteLink na maquina **alvo** (quem vai ser controlado)
2. Na pagina **Compartilhar**, clique em "Iniciar servidor"
3. Anote o codigo de acesso exibido no banner (ex: `078-509`)
4. Na maquina **viewer** (quem vai controlar), va ate **Conectar**
5. Digite o codigo, IP ou hostname do alvo e clique em "Verificar"
6. Confirme as informacoes e clique em "Conectar"

### Controle remoto

- **Mouse sobre o video** → modo REMOTO ativado (mouse e teclado controlam o alvo)
- **Mouse fora do video** → modo LOCAL (teclado volta ao sistema local)
- Clique no indicador `REMOTO` / `Local` na toolbar para alternar manualmente

### Atalhos na toolbar

| Botao | Funcao |
|-------|--------|
| Alt+Tab | Alternar janelas no remoto |
| Win | Abrir menu iniciar |
| Ctrl+Alt+Del | Enviar sequencia de seguranca |
| PrtScr | Capturar tela remota |
| Ctrl+C / V / Z / W | Atalhos comuns |

---

## Build .EXE

Gera um executavel standalone para Windows sem necessidade de Python instalado.

```bash
pip install pyinstaller
python build.py                  # Arquivo unico (padrao)
python build.py --onedir         # Pasta (inicia mais rapido)
python build.py --debug          # Com console para debug
python build.py --clean          # Limpa artefatos de build
```

O executavel sera criado em `dist/RemoteLink.exe` (~40-80MB).

> **Nota:** Na primeira execucao o Windows Defender pode alertar (sem assinatura digital). Clique em "Mais informacoes > Executar assim mesmo".

---

## Arquitetura

### Visao geral

```
+------------------+          TCP/IP          +------------------+
|                  |   52340 (frames)         |                  |
|   VIEWER         |<=========================|   HOST           |
|   (cliente)      |   52341 (input)          |   (servidor)     |
|                  |=========================>|                  |
+------------------+                          +------------------+
```

### Componentes

| Modulo | Responsabilidade |
|--------|-----------------|
| `main.py` | Ponto de entrada — inicializa a GUI |
| `gui/app.py` | Interface Tkinter completa com tema escuro |
| `core/identity.py` | Geracao de codigo, deteccao de IPs, scan de rede |
| `core/server.py` | Servidor: captura de tela + recepcao de input |
| `core/client.py` | Cliente: recepcao de frames + envio de input |

### Sobre os sockets

Cada sessao utiliza **dois sockets TCP separados** para eliminar race conditions:
- **Porta 52340** — fluxo continuo de frames JPEG do host para o viewer
- **Porta 52341** — eventos de input (mouse/teclado) do viewer para o host

---

## Protocolo

### Handshake

```
[Viewer] --TCP connect--> [Host:52340]
[Viewer] --{version, access_code, probe} JSON-->
[Host]   --{status, machine, session_id, input_port} JSON-->
```

### Stream de frames

```
[Host] --header(1 byte type + 4 bytes len + 4 bytes timestamp) + JPEG data-->
```

O host captura a tela a ~60 FPS usando `mss`, codifica em JPEG (qualidade 70, subamostragem 4:4:4) e envia em streaming continuo.

### Input

```
[Viewer] --header(1 byte type + 4 bytes len) + JSON event-->
```

Tipos de evento: `mouse_move`, `mouse_click`, `mouse_scroll`, `key_down`, `key_up`, `type_text`.

---

## Estrutura do projeto

```
RemoteLink/
├── main.py                 # Ponto de entrada
├── requirements.txt        # Dependencias pip
├── build.py                # Script de build PyInstaller
├── RemoteLink.spec         # Spec gerado pelo PyInstaller
├── README.md               # Voce esta aqui
│
├── core/                   # Logica central
│   ├── __init__.py
│   ├── identity.py         # Codigo de acesso, IPs, scan de rede
│   ├── server.py           # Servidor host (captura + input)
│   └── client.py           # Cliente viewer (frames + input)
│
├── gui/                    # Interface grafica
│   ├── __init__.py
│   └── app.py              # App Tkinter completa
│
├── assets/                 # Recursos
│   ├── icon.ico            # Icone do aplicativo
│   └── icon_256.png        # PNG para preview
│
├── build/                  # Artefatos de build (gerado)
└── dist/                   # Executavel final (gerado)
```

---

## Seguranca

- **Autenticacao por codigo** — O host so aceita conexoes com o codigo correto
- **Sessao unica** — Apenas 1 cliente por vez
- **Rede local apenas** — Sem relay externo, sem servidores na nuvem
- **Auto-restricao** — O sistema impede conexao com a propria maquina
- **Sockets separados** — Isolamento entre canal de video e canal de input
- **VPN recomendada** — Para ambientes nao confiaveis, use uma VPN

---

## Solucao de problemas

### "Connection refused"

O RemoteLink nao esta rodando no alvo ou o servidor nao foi iniciado.

1. Abra o RemoteLink no computador alvo
2. Va ate a pagina **Compartilhar**
3. Clique em "Iniciar servidor"
4. Verifique se aparece "Aguardando conexoes"

### "Nao e possivel conectar a si mesmo"

Voce digitou seu proprio IP ou codigo. Use o codigo, IP ou hostname de **outro computador** na rede.

### Firewall bloqueando

Libere as portas `52340` e `52341` no firewall do Windows:

```
Windows Defender Firewall > Configuracoes avancadas > Regras de Entrada
> Nova Regra > Porta > TCP > 52340, 52341 > Permitir
```

### Hostname nao resolve

Use o IP diretamente ou verifique se o DNS local esta configurado corretamente.

### Tela nao aparece / frame preto

Instale as dependencias de captura:

```bash
pip install mss Pillow
```

### Latencia alta

- O RemoteLink e otimizado para rede local (LAN)
- Em WiFi, mantenha ambos proximos ao roteador
- O FPS alvo e 60, mas pode cair em maquinas mais lentas

---

## Licenca

MIT License — use, modifique e distribua livremente.
