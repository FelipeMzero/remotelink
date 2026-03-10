<div align="center">

# 🔗 RemoteLink

**Acesso remoto via rede local — alternativa open-source ao AnyDesk, feita em Python puro**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Status](https://img.shields.io/badge/Status-Em%20desenvolvimento-yellow?style=flat-square)

</div>

---

## 📸 Sobre o projeto

RemoteLink é uma aplicação desktop de acesso remoto construída do zero em Python, com interface moderna no estilo **Windows 11 Fluent Design**. O objetivo é oferecer uma alternativa leve e open-source para controle remoto de máquinas em rede local, sem depender de servidores externos ou assinaturas pagas.

Cada máquina recebe um **código de acesso único** gerado a partir do hardware (MAC address + hostname), no formato `XXX-XXX-XXX`, que permanece estável entre reinicializações.

---

## ✨ Funcionalidades

- 🔑 **Código de acesso único por máquina** — gerado automaticamente, sem cadastro
- 🖥 **3 modos de conexão:**
  - Por código de acesso (`ABC-DEF-GHI`)
  - Por IP direto (`192.168.1.50`)
  - Por hostname (`SERVIDOR01`, `PC-JOAO`) — funciona em redes com Windows Server / Active Directory
- 🔍 **Pré-visualização antes de conectar** — veja OS, hostname e IP do alvo antes de confirmar
- 📡 **Descoberta automática** — escaneia a rede local em busca de máquinas com RemoteLink ativo
- 🖱 **Controle completo** — mouse, teclado, scroll, duplo clique, atalhos (Ctrl+Alt+Del, Win, Alt+Tab)
- 🎨 **Interface Fluent Design** — tema claro, cards, navegação lateral, tipografia Segoe UI Variable
- 📦 **Exportável para `.exe`** — via PyInstaller, sem dependências externas

---

## 🚀 Instalação

### Pré-requisitos

- Python 3.10 ou superior
- pip

### 1. Clone o repositório

```bash
git clone https://github.com/FelipeMzero/remotelink.git
cd remotelink
```

### 2. Instale as dependências

```bash
pip install -r requirements.txt
```

| Pacote | Função |
|--------|--------|
| `Pillow` | Processamento de frames JPEG |
| `mss` | Captura de tela (lado host) |
| `pyautogui` | Controle de mouse e teclado (lado host) |

### 3. Execute

```bash
python main.py
```

---

## 🏗 Gerar executável `.exe`

```bash
pip install pyinstaller
python build.py
```

O arquivo `dist/RemoteLink.exe` é gerado standalone (~60–80 MB), sem necessidade de Python instalado na máquina de destino.

---

## 📁 Estrutura do projeto

```
remotelink/
├── main.py              # Ponto de entrada
├── requirements.txt     # Dependências Python
├── build.py             # Script PyInstaller
├── core/
│   ├── identity.py      # Código único de máquina + descoberta de rede
│   ├── server.py        # Servidor: captura de tela + recebe input remoto
│   └── client.py        # Cliente: recebe frames + envia mouse/teclado
└── gui/
    └── app.py           # Interface Tkinter — Fluent Design
```

---

## 🔌 Protocolo de rede

- **Porta:** `52340` TCP
- Handshake JSON com validação de código de acesso
- Stream de frames JPEG comprimidos (~15 fps por padrão)
- Eventos de input em JSON (mouse move, click, scroll, teclado)

```
[Viewer] ──TCP connect──▶ [Host:52340]
[Viewer] ──{version, access_code}──▶
         ◀──{status: accepted, machine: {...}}──
[Host]   ──JPEG frame stream──▶
[Viewer] ──input events (mouse/keyboard)──▶
```

---

## 🔒 Segurança

- Conexões validadas por código de acesso único por máquina
- Servidor aceita apenas **um cliente por vez**
- **Sem relay externo** — todo o tráfego fica na rede local (LAN/VPN)
- Para ambientes sensíveis, recomenda-se uso em VPN ou rede privada isolada

---

## 🛠 Solução de problemas

| Problema | Solução |
|----------|---------|
| `Connection refused` | Certifique-se que o RemoteLink está rodando no PC alvo e o servidor foi iniciado |
| Firewall bloqueando | Libere a porta `52340` no Windows Defender / firewall da rede |
| Hostname não resolve | Use o IP diretamente, ou verifique a configuração de DNS local |
| Tela não aparece | Instale `mss` e `Pillow`: `pip install mss Pillow` |
| Erro no `.exe` | Use `--console` no PyInstaller para ver logs de erro detalhados |

---

## 🤝 Contribuindo

Contribuições são bem-vindas! Sinta-se à vontade para abrir issues, sugerir funcionalidades ou enviar pull requests.

1. Fork o projeto
2. Crie sua branch: `git checkout -b feature/minha-feature`
3. Commit: `git commit -m 'feat: adiciona minha feature'`
4. Push: `git push origin feature/minha-feature`
5. Abra um Pull Request

---

## 📋 Roadmap

- [ ] Transferência de arquivos entre máquinas
- [ ] Criptografia end-to-end (TLS)
- [ ] Múltiplos monitores
- [ ] Histórico de conexões
- [ ] Autenticação por senha além do código
- [ ] Suporte a relay externo (conexão fora da LAN)
- [ ] Versão mobile (viewer)

---

## 📄 Licença

Distribuído sob a licença MIT. Veja [`LICENSE`](LICENSE) para mais informações.

---

<div align="center">
Feito com Python 🐍 por <a href="https://github.com/seu-usuario">Felipe Monteiro</a>
</div>
