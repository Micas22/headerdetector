# Header Detector

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-Web%20Framework-000000.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009485.svg)
![Playwright](https://img.shields.io/badge/Playwright-Crawler-2EAD33.svg)
![BeautifulSoup](https://img.shields.io/badge/BeautifulSoup-HTML%20Parser-E34F26.svg)
![Docker](https://img.shields.io/badge/Docker-Container-2496ED.svg)

O **Header Detector** é uma ferramenta especializada de web scraping e auditoria de SEO projetada para validar a estrutura de cabeçalhos (H1-H6) de páginas da web. Ele garante que as páginas sigam as melhores práticas de acessibilidade e SEO, aplicando a regra de um único H1 e hierarquia estrita de cabeçalhos.

---

### Executando com Docker (Recomendado)

Certifique-se de ter [Docker](https://docs.docker.com/install/) e [Docker Compose](https://docs.docker.com/compose/install/) instalados em sua máquina.

```bash
# 1. Clone ou navegue para o diretório do projeto
cd headerdetector

# 2. Inicie a aplicação com Docker Compose
docker-compose up

# 3. Acesse a aplicação
# UI estará disponível em http://localhost:5000
# API estará disponível em http://localhost:8000
# Documentação interativa da API em http://localhost:8000/docs
```

---

## API Endpoints

### FastAPI (Port 8000)

A API FastAPI fornece os seguintes endpoints:

#### POST /api/audit
Audita uma lista de URLs e retorna os resultados.

**Request:**
```json
{
  "urls": ["https://example.com", "https://another.com"]
}
```

**Response:**
```json
{
  "results": [
    {
      "url": "https://example.com",
      "pass": true,
      "h1_pass": true,
      "h1_count": 1,
      "h1_is_image": false,
      "hierarchy_pass": true,
      "heading_count": 5,
      "warning_count": 0,
      "tree": [...],
      "issues": []
    }
  ]
}
```

#### POST /api/audit-paginated
Audita URLs com paginação, retornando resultados em tempo real via Server-Sent Events (SSE).

**Request:**
```json
{
  "listing_urls": ["https://example.com/page1", "https://example.com/page2"]
}
```

#### GET /health
Verifica o status da API.

**Response:**
```json
{
  "status": "ok"
}
```

#### GET /docs
Documentação interativa da API (Swagger UI).

#### GET /redoc
Documentação alternativa da API (ReDoc).

---