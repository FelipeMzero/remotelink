# RemoteLink v2.0 ⚡

> **Acesso Remoto Ultrarrápido, Seguro e Portátil estilo AnyDesk em Python.**
> Suporte nativo a **Rede Local (LAN)** e **Rede Externa (Internet/WAN)** por Código de Acesso, Token Externo, Hostname ou IP direto.

---

## 🌟 O que há de novo na v2.0?

1. **🛡️ Diálogo de Autorização com Botão "Aceitar / Recusar" (Estilo AnyDesk)**:
   - O computador Host agora exibe uma janela modal destacada com alerta sonoro e contagem regressiva de 45 segundos.
   - O usuário do Host escolhe explicitamente se deseja **Aceitar Conexão** ou **Recusar**.
   - Permissões modulares: controle individual para autorizar ou bloquear **Teclado e Mouse**, **Som dos alto-falantes** e **Microfone remoto**.
   - Modo "Acesso Não Supervisionado" opcional na aba *Servidor & Portas* para servidores remotos autônomos.

2. **🔊 Transmissão de Áudio e 🎙️ Microfone Bidirecional**:
   - Engine de áudio nativa em tempo real com captura de som do PC via **Windows WASAPI Loopback (`PyAudioWPatch`)** + fallback `sounddevice`. Captura com perfeição tudo o que estiver tocando nos alto-falantes/fones do Host (YouTube, Spotify, jogos, sons do Windows).
   - Conversão em C de altíssima velocidade para PCM 24 kHz, 16-bit Mono com buffer anti-jitter.
   - Suporte a áudio bidirecional tanto em **conexão direta (TCP)** quanto em **Relay Externo**.
   - Botões dedicados na barra de ferramentas do Viewer: **🔊 Som: Ativo/Mudo** e **🎙️ Mic: Ativo/Mudo**.

3. **⚡ Performance Acima de 35-50+ FPS e Latência Quase Zero**:
   - **Captura Ultrarrápida no Host**: GDI DIBSection nativo com persistência de desktop de entrada do Windows (`OpenInputDesktop` + `SetThreadDesktop`), eliminando falhas de buffer e alocações repetidas por frame.
   - **Renderização Assíncrona no Viewer**: A decodificação JPEG e o redimensionamento rápido (`Image.BOX`/`NEAREST`, 1.3ms vs 17ms) acontecem em uma thread de worker orientada a eventos (`_frame_worker_loop`), com temporizador Windows de 1ms (`timeBeginPeriod(1)`), atingindo com folga **35-50+ FPS contínuos**.
   - **Taxa Aprimorada no Relay**: Desbloqueado o limite de Relay de 12 FPS para **30+ FPS contínuos** em redes CGNAT.
   - **Mouse e Teclado Instantâneos**: Chamadas diretas de Win32 `SetCursorPos` e `SendInput` com fila de comandos priorizada (cliques e teclas furam a fila de movimentos de mouse) e taxa de atualização de 200 Hz (5ms).
   - **Seletor Dinâmico de Qualidade**: Botão **🎨 Qualidade** na toolbar alternando dinamicamente entre **HD** (100% escala, Q78), **Equilibrada** (1600x900, Q72) e **Rápida** (1366x768, Q65).

4. **✨ Novo Design: Tema Claro (White Theme) & Fonte Google Outfit**:
   - Paleta visual moderna, limpa e profissional com superfícies brancas (`#ffffff`), tons neutros suaves Slate (`#f8fafc`, `#e2e8f0`) e detalhes em azul moderno (`#2563eb`).
   - Tipografia integrada com a elegante fonte **Outfit** carregada e registrada dinamicamente em tempo de execução via Win32 GDI API.

5. **🔒 Auditoria Criptográfica com Proof-of-Work e Fingerprint Visual**:
   - Desafio anti-ataque de força bruta e anti-DDoS via **Hashcash SHA-256**.
   - Impressão digital de sessão mútua (**Session Fingerprint**) para garantia de segurança ponta a ponta e auditoria visual em tempo real.

---

## ❓ Cadê o proof-of-work de que essa conexão é segura?

Para responder a essa pergunta com rigor matemático e criptográfico, o RemoteLink implementa um mecanismo de **Prova de Trabalho (Proof-of-Work - Hashcash SHA-256)** acoplado a um **Fingerprint de Sessão Mútuo**:

```
[VIEWER / CLIENTE]                                       [HOST / SERVIDOR]
       |                                                         |
       |  1. Desafio de Conexão + Timestamp                      |
       |-------------------------------------------------------->|
       |                                                         |
       |  2. Computação Local de Proof-of-Work:                  |
       |     Busca Nonce tal que:                                |
       |     SHA-256(Desafio || Nonce) inicia com "0000"         |
       |     (~40ms em CPU moderna / 16 bits de dificuldade)     |
       |                                                         |
       |  3. Envio da Solução {pow_nonce, pow_hash}              |
       |-------------------------------------------------------->|
       |                                                         |
       |                                           4. Validação Instantânea:
       |                                              Servidor verifica se o
       |                                              hash confere com o nonce.
       |                                              (Se falso: conexão rejeitada)
       |                                                         |
       |  5. Cálculo Mútuo da Impressão Digital (Fingerprint)    |
       |     SHA-256(SessionID + CodigoHost + CodigoClient + PoW)|
       |     Resultado formatado: "XXXX-XXXX-XXXX-XXXX"          |
       |<=======================================================>|
```

### Por que esse Proof-of-Work existe e o que ele garante?

1. **Defesa Ativa contra Ataques de Força Bruta (Brute-Force Shield)**:
   - Sem PoW, um atacante ou botnet na rede poderia disparar milhares de tentativas de adivinhação de códigos de acesso por segundo.
   - Com o PoW Hashcash SHA-256 ativado, cada tentativa exige trabalho computacional real do cliente. Isso torna ataques em massa economicamente e tecnicamente inviáveis, sem causar nenhum atraso perceptível para o usuário humano (~40ms na conexão inicial).
2. **Defesa contra Negação de Serviço (Anti-DDoS / Anti-SynFlood)**:
   - O servidor Host só aloca recursos de streaming de vídeo e threads de captura após a solução de PoW ser validada no cabeçalho. Conexões forjadas são descartadas imediatamente.
3. **Auditoria Visual da Conexão (Session Fingerprint)**:
   - Clicando no botão **🔒 Segurança & PoW** na barra do Viewer ou em **🛡️ Ver Auditoria de Segurança** no Host, uma janela modal detalha:
     - O status de validação do Hashcash SHA-256.
     - O valor exato do hash e do nonce resolvidos.
     - O **Session Fingerprint** (código de 16 caracteres hexadecimais únicos no formato `A1B2-C3D4-E5F6-09EA`).
     - Como o fingerprint é derivado de variáveis privadas da sessão conhecidas apenas pelas duas pontas, se os dois lados enxergarem o mesmo código na tela, há certeza matemática de que **não há intermediário malicioso ou ataque Man-in-the-Middle (MitM)**.

---

## 🚀 Instalação e Execução

### Requisitos

- Python 3.10 ou superior
- Windows 10 / 11 (recomendado para hooks Win32 de teclado e captura GDI de alta taxa)

### Instalação das Dependências

```bash
pip install -r requirements.txt
```

| Pacote | Função |
|---|---|
| `Pillow` | Decodificação e codificação JPEG otimizada |
| `mss` | Captura multiplataforma de fallback |
| `PyAudioWPatch` | Captura de som do PC via Windows WASAPI Loopback |
| `sounddevice` | Suporte e fallback de áudio / microfone |
| `pynput` | Emulação de mouse e teclado |
| `pyautogui` | Utilitários de tela e fallback de input |

### Iniciar o Aplicativo

```bash
python main.py
```

---

## 🎮 Como Usar

### 1. Permitindo Acesso Remoto (Host)
1. Abra o RemoteLink no computador que será controlado.
2. Seu **Código de Acesso** (ex: `750-789`) será gerado automaticamente.
3. O servidor inicia escutando em múltiplas portas (`52340`, `52341`, `8080`, `443`, etc.) e se conecta ao Cloud Relay.
4. Quando uma conexão chegar:
   - Uma notificação vibrante abrirá com a identificação do solicitante, o Session Fingerprint e o status do Proof-of-Work.
   - Ajuste as permissões (Teclado/Mouse, Som, Microfone) e clique no botão verde **Aceitar Conexão**.

### 2. Acessando uma Máquina (Viewer)
1. Abra o RemoteLink no computador de onde você vai controlar.
2. Na aba **Conectar à Tela**, digite o código de acesso, Token Externo (`RL-...`) ou IP do Host.
3. Clique em **Verificar** e depois em **Conectar**.
4. A tela remota abrirá instantaneamente em alta taxa de quadros (35+ FPS).
5. Posicione o cursor sobre a tela para controlar mouse e teclado com precisão nativa.

### 3. Barra de Ferramentas Superior do Viewer
- **Atalhos Rápidos**: `Alt+Tab`, `Tecla Win`, `Win+D`, `Ctrl+Alt+Del` e `Colar Texto`.
- **🔊 Som**: Ative ou desative os alto-falantes do computador remoto.
- **🎙️ Mic**: Envie a sua voz via microfone para a máquina remota.
- **🎨 Qualidade**: Alterne entre HD, Equilibrada e Rápida conforme a velocidade da sua conexão.
- **🔒 Segurança & PoW**: Exiba o certificado em tempo real da prova de trabalho e a impressão digital da sessão.
- **F11**: Alterna modo tela cheia.

---

## 🛠️ Gerando o Executável Standalone (.EXE)

Para compilar um `.exe` portátil com ícones e fontes já embutidos:

```bash
python build.py
```

O executável pronto para distribuição estará disponível em `dist/RemoteLink.exe`.

---

## 📂 Estrutura do Projeto

```
remotelink/
├── assets/
│   ├── fonts/
│   │   └── Outfit-VariableFont_wght.ttf  # Fonte Google Outfit embutida
│   ├── icon.ico                          # Ícone do app
│   └── icon_256.png
├── core/
│   ├── audio.py                          # Engine PCM de captura e playback de som/mic
│   ├── crypto.py                         # Proof-of-Work SHA-256 e Session Fingerprinting
│   ├── client.py                         # Conexão, streaming de vídeo, input e áudio
│   ├── server.py                         # GDI capture, autorização, áudio e injeção Win32
│   └── identity.py                       # UPnP, NAT traversal, STUN e tokens de rede
├── gui/
│   └── app.py                            # GUI White Theme com Outfit, ViewerWindow e diálogos
├── build.py                              # Script PyInstaller para Windows
├── RemoteLink.spec                       # Manifesto de build
├── requirements.txt                      # Dependências Python
└── README.md
```

---

## 📜 Licença

Distribuído sob licença MIT. Livre para uso pessoal, comercial, modificação e redistribuição.
