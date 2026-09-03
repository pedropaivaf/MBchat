# MB Chat - Integração com VPS, Bots & Automações Contábeis

Este documento detalha a arquitetura e as especificações para a integração do **MBchat** com servidores **VPS**, **Assistentes de IA (ChatGPT, Claude)** e **Automações de Escritório Contábil** via comandos no estilo CLI.

---

## 🎯 Visão Geral da Arquitetura

Para manter a privacidade da rede P2P local e a simplicidade do executável standalone sem expor chaves de API nos clientes, a integração utiliza uma **VPS Gateway** (ou Servidor Local Headless) atuando como um "Nó de Serviço" na rede do MBchat.

```
+------------------+         P2P TCP / Webhook         +--------------------+
|  MBchat Client   | <===============================> |  VPS Bot Gateway   |
| (Analista / LAN) |                                   | (Daemon Python)    |
+------------------+                                   +--------------------+
         |                                                       |
         | /cnpj, /cnd, /resumir-pdf, /rpa                       | APIs Externas
         v                                                       v
+------------------+                                   +--------------------+
| Execução de CLI  |                                   | Receita Federal,   |
| & Comandos Chat  |                                   | Sefaz, Claude, GPT |
+------------------+                                   +--------------------+
```

---

## 🤖 1. Comandos CLI e Assistente de IA Contábil

Os usuários interagem diretamente na janela do chat enviando mensagens iniciadas por `/` ou mencionando `@bot` / `@ia`.

### Comandos de Consulta Fiscais e Societários:
* **`/cnpj [número]`**: Consulta a API da Receita Federal/Sintegra. Retorna Razão Social, Regime Tributário, CNAEs e Situação Cadastral.
* **`/cnd [cnpj]`**: Verifica e emite Certidões Negativas (Federal, FGTS, Trabalhista, Estadual) devolvendo o status ou o PDF no chat.
* **`/nfe [chave]`**: Consulta situação de Notas Fiscais na Sefaz (Autorizada, Cancelada).
* **`/calculo [tipo] [valores]`**: Simulações rápidas de impostos (DAS Simples Nacional, Retenções na Fonte, Rescisão/Férias DP).

### Assistente de Documentos com IA:
* **`/resumir-pdf` / `/analisar-balancete`**: O analista envia um arquivo PDF e digita o comando. A VPS processa o arquivo via LLM (Claude/ChatGPT) e gera um resumo executivo com pontos de atenção, variações patrimoniais atípicas e alertas fiscais.

---

## 📊 2. Processamento Automático de Arquivos (OFX / XML)

Ao enviar arquivos na conversa privada ou de grupo, o Bot lê a extensão e responde com **Cards de Resumo**:

* **Arquivos Extrato bancário (`.OFX`):** Totaliza Entradas, Saídas, Saldo do período e validação de compatibilidade com o sistema contábil.
* **Pacotes de Notas Fiscais (`.XML` / `.ZIP`):** Contagem de notas autorizadas/canceladas, faturamento total do lote e estimativa prévia de impostos.

---

## ⏰ 3. Agenda Fiscal Automática & Lembretes de Setor

Integrado à infraestrutura de Reuniões e Lembretes do MBchat:

* **Alertas Programados:** Envio de lembretes automáticos nos chats de grupos dos setores (Fiscal, DP, Contábil) para datas críticas de guias e declarações (DAS dia 20, eSocial/Folha dia 15, DCTFWeb, EFD-Reinf).
* **Check-list de Entrega:** Comandos rápidos tipo `/ok das [código_cliente]` para marcar pendências entregues.

---

## ⚡ 4. Robôs de Automação (RPA) & Infraestrutura

* **`/rpa guias --cliente [código]`**: A VPS dispara robôs headless (Selenium/Playwright) que emitem guias em portais do eCAC ou prefeituras e entregam os PDFs direto no chat do analista.
* **`/status servidor`**: Monitoramento de espaço em disco, conectividade Sefaz e banco de dados dos sistemas contábeis.

---

## 🛠️ Especificação de Tipos de Mensagens (Rede)

Para suportar essas automações, novos tipos de mensagens de protocolo serão adicionados ao `network.py`:

* `MT_COMMAND`: Envio de comando CLI pelo usuário para um Bot (`/comando args`).
* `MT_BOT_CARD`: Resposta formatada do Bot com suporte a botões de ação e tabelas ricas.
