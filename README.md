# Header Detector

[English](#english) | [Português](#portugues)

---

<a id="english"></a>
## English Version

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-Web%20Framework-000000.svg)
![Playwright](https://img.shields.io/badge/Playwright-Crawler-2EAD33.svg)
![BeautifulSoup](https://img.shields.io/badge/BeautifulSoup-HTML%20Parser-E34F26.svg)

**Header Detector** is a specialized web scraping and SEO auditing tool designed to validate the heading structure (H1-H6) of web pages. It ensures pages adhere to accessibility and SEO best practices by enforcing a single H1 rule and strict heading hierarchy. The project includes a Flask web interface with real-time Server-Sent Events (SSE) streaming and a robust Playwright-based crawler.

---

### Key Features

- **Strict Hierarchy Validation:** Ensures heading levels are not skipped downwards (e.g., H1 to H3 is invalid, but H3 to H2 is allowed).
- **Single H1 Enforcement:** Validates that each page contains exactly one H1 tag.
- **Image Accessibility Check:** Identifies image-only headings and verifies the presence of `alt` text for screen readers.
- **Versatile Crawling Modes:**
  - **Single Page Audit:** Analyze individual URLs.
  - **Paginated Listing Audit:** Auto-detect pagination, harvest item links from listings (e.g., news or events), and audit every detail page.
  - **Whole Site Audit:** Perform a Breadth-First Search (BFS) crawl to map and audit an entire domain.
- **Live Progress Streaming:** Uses Server-Sent Events (SSE) to stream live progress and results directly to the frontend.
- **Playwright Integration:** Maintains a persistent browser session for fast, JavaScript-enabled rendering and extraction.

---

### Architecture & Tech Stack

- **Backend / API:** Flask (Python)
- **Scraping / Crawling:** Playwright, BeautifulSoup4, Requests
- **Streaming:** Server-Sent Events (SSE)
- **Frontend / UI:** HTML/CSS with Jinja templates (served by Flask)

---

### Getting Started

#### Running Locally

```bash
# 1. Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

# 2. Install dependencies
# (Ensure Flask, Playwright, BeautifulSoup4, and Requests are installed)
pip install flask playwright beautifulsoup4 requests

# 3. Install Playwright browsers
playwright install chromium

# 4. Start the application
python app.py
```
*The Flask server will start on `http://localhost:5000` with multi-threading enabled for concurrent crawling and SSE streaming.*

---

### How to Use the UI

1. **Open the Dashboard:** Navigate to `http://localhost:5000`.
2. **Select Audit Mode:**
   - **Single URL:** Paste URLs to check individual pages immediately.
   - **Paginated Audit:** Provide a listing page URL. The crawler will find all pages, extract item links, and audit them.
   - **Site Audit:** Provide a root URL to automatically discover and check all same-domain pages.
3. **Review Results:** The application will stream results in real-time. Look out for:
   - **Errors:** Missing H1, multiple H1s, or skipped hierarchy levels.
   - **Warnings:** Image-only headings missing `alt` attributes.

---

### Project Structure

- `app.py`: Flask web server, API routing, and Server-Sent Events (SSE) generation.
- `checker.py`: Core logic for validating the single H1 rule, hierarchy progression, and image-heading accessibility.
- `crawler.py`: Handles Playwright browser sessions, HTML parsing, pagination detection, and link extraction.
- `templates/`: Contains the frontend HTML and UI views.

---
*Built with passion for accessible and structurally sound web pages.*

<br><br>

---

<a id="portugues"></a>
## Versão em Português

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-Web%20Framework-000000.svg)
![Playwright](https://img.shields.io/badge/Playwright-Crawler-2EAD33.svg)
![BeautifulSoup](https://img.shields.io/badge/BeautifulSoup-HTML%20Parser-E34F26.svg)

O **Header Detector** é uma ferramenta especializada de web scraping e auditoria de SEO projetada para validar a estrutura de cabeçalhos (H1-H6) de páginas da web. Ele garante que as páginas sigam as melhores práticas de acessibilidade e SEO, aplicando a regra de um único H1 e hierarquia estrita de cabeçalhos. O projeto inclui uma interface web em Flask com transmissão em tempo real via Server-Sent Events (SSE) e um rastreador robusto baseado em Playwright.

---

### Principais Funcionalidades

- **Validação de Hierarquia Estrita:** Garante que os níveis de cabeçalho não sejam pulados para baixo (por exemplo, H1 para H3 é inválido, mas H3 para H2 é permitido).
- **Aplicação de H1 Único:** Valida se cada página contém exatamente uma tag H1.
- **Verificação de Acessibilidade de Imagens:** Identifica cabeçalhos contendo apenas imagens e verifica a presença de texto alternativo (`alt`) para leitores de tela.
- **Modos Versáteis de Rastreamento:**
  - **Auditoria de Página Única:** Analise URLs individuais.
  - **Auditoria de Listagem Paginada:** Detecte paginação automaticamente, colete links de itens de listagens (como notícias ou eventos) e audite cada página de detalhes.
  - **Auditoria de Site Completo:** Execute um rastreamento em Largura (BFS) para mapear e auditar um domínio inteiro.
- **Transmissão de Progresso ao Vivo:** Usa Server-Sent Events (SSE) para transmitir o progresso e os resultados ao vivo diretamente para o frontend.
- **Integração com Playwright:** Mantém uma sessão de navegador persistente para renderização e extração rápidas, mesmo em páginas renderizadas via JavaScript.

---

### Arquitetura e Tecnologias

- **Backend / API:** Flask (Python)
- **Scraping / Crawling:** Playwright, BeautifulSoup4, Requests
- **Transmissão:** Server-Sent Events (SSE)
- **Frontend / UI:** HTML/CSS com templates Jinja (servidos pelo Flask)

---

### Primeiros Passos

#### Executando Localmente

```bash
# 1. Crie um ambiente virtual
python -m venv venv
source venv/bin/activate  # No Windows use: venv\Scripts\activate

# 2. Instale as dependências
# (Certifique-se de que Flask, Playwright, BeautifulSoup4 e Requests estejam instalados)
pip install flask playwright beautifulsoup4 requests

# 3. Instale os navegadores do Playwright
playwright install chromium

# 4. Inicie a aplicação
python app.py
```
*O servidor Flask será iniciado em `http://localhost:5000` com suporte a múltiplas threads para rastreamento simultâneo e transmissão SSE.*

---

### Como usar a Interface do Usuário

1. **Abra o Painel:** Navegue para `http://localhost:5000`.
2. **Selecione o Modo de Auditoria:**
   - **URL Única:** Cole URLs para verificar páginas individuais imediatamente.
   - **Auditoria Paginada:** Forneça a URL de uma página de listagem. O rastreador encontrará todas as páginas, extrairá os links dos itens e os auditará.
   - **Auditoria de Site:** Forneça uma URL raiz para descobrir e verificar automaticamente todas as páginas do mesmo domínio.
3. **Revise os Resultados:** A aplicação transmitirá os resultados em tempo real. Fique atento a:
   - **Erros:** H1 ausente, múltiplos H1s ou níveis de hierarquia pulados.
   - **Avisos:** Cabeçalhos contendo apenas imagens sem o atributo `alt`.

---

### Estrutura do Projeto

- `app.py`: Servidor web Flask, roteamento de API e geração de Server-Sent Events (SSE).
- `checker.py`: Lógica central para validar a regra de H1 único, progressão hierárquica e acessibilidade de cabeçalhos com imagens.
- `crawler.py`: Lida com sessões do navegador Playwright, análise de HTML, detecção de paginação e extração de links.
- `templates/`: Contém o HTML do frontend e as visualizações da interface do usuário.

---
*Construído com paixão para páginas web acessíveis e estruturalmente sólidas.*
