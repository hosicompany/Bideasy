# BidEasy

**Mobile-first public bid assistant** - Data-driven management and analysis for the Korean public bidding market.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Flutter (Riverpod, Toss-style design system) |
| Backend | FastAPI, LangChain, Celery + Redis |
| Database | PostgreSQL (prod) / SQLite (dev) |
| AI | OpenAI API (gpt-4o-mini) |
| Infra | Docker Compose, GitHub Actions CI/CD |

## Quick Start

### Backend

```bash
cd backend
pip install -r requirements.txt

# Configure environment
cp .env.example .env   # edit with your API keys

python main.py
# Server runs at http://127.0.0.1:8000
```

### Frontend

```bash
cd frontend
flutter pub get
flutter run
```

### Docker (Full Stack)

```bash
cd infra
docker compose up -d
```

## Project Structure

```
01_Bid Easy/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/   # Route handlers
│   │   ├── core/               # Config, security, logging, cache
│   │   ├── db/                 # Models, sessions, migrations
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   └── services/           # Business logic (calculator, crawler, LLM)
│   ├── models/                 # ML model files (.joblib)
│   ├── tests/                  # pytest test suite
│   └── main.py
├── frontend/
│   └── lib/
│       ├── models/             # Data models
│       ├── providers/          # Riverpod state management
│       ├── screens/            # Page widgets
│       ├── services/           # API client
│       ├── theme/              # Design tokens and styles
│       ├── utils/              # Shared utilities
│       └── widgets/            # Reusable UI components
├── infra/                      # Docker Compose config
├── .github/workflows/          # CI/CD pipeline
└── docs/                       # Documentation
```

## Testing

```bash
# Backend (38 tests)
cd backend && python -m pytest tests/ -v

# Frontend (66 tests)
cd frontend && flutter test

# Static analysis
cd frontend && flutter analyze
```

## Key Features

- **Smart Feed** - Filtered public bid listings with real-time crawling
- **Bid Calculator** - Safety-checked bid price calculation with legal compliance
- **AI Analysis** - GPT-powered bid document summarization and risk detection
- **Deep Analysis** - Attachment file (HWP/PDF) toxic clause detection
- **Competition Prediction** - ML-based bidder count and rate prediction
- **Agency Profiling** - Historical agency behavior analysis
