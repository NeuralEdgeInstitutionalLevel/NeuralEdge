# Trading Bot SaaS Platform -- Full Plan
# ========================================
# Saved: 2026-03-23
# Status: PLANNING (build after V3 track record)

## 1. Business Model

### Pricing Tiers

| Tier | Price | What They Get |
|------|-------|---------------|
| **Starter** | $199/mo | Signals only (Telegram/webhook), 3 pairs max |
| **Pro** | $499/mo | Full dashboard + auto-execution on their Bitget account, all 24 pairs |
| **Elite** | $999/mo | Pro + priority support + custom risk settings + early access to upgrades |
| **Managed** | 20% profit share | We run everything, they just deposit capital (min $5000) |

### Revenue Projections (conservative)
- 20 Starter users = $3,980/mo
- 10 Pro users = $4,990/mo
- 5 Elite users = $4,995/mo
- Total potential: ~$14K/mo with just 35 users

---

## 2. Architecture Overview

```
[CloudFlare DNS + CDN]
         |
[Frontend - Vercel/Netlify]     (Next.js React app)
         |
[Backend API - FastAPI]          (VPS with GPU)
    |         |         |
[PostgreSQL] [Redis]  [Trading Engine]
    |                   |
[Stripe]          [Bitget API per user]
```

### Why This Stack
- **Next.js**: Fast, SEO-friendly landing page + React dashboard
- **FastAPI**: Python (same language as bot, easy integration)
- **PostgreSQL**: Users, subscriptions, trade history, PnL
- **Redis**: Real-time signal broadcasting, session cache
- **Stripe**: Industry standard payments, handles subscriptions automatically
- **CloudFlare**: DDoS protection, SSL, caching

---

## 3. Database Schema

```sql
-- Users
CREATE TABLE users (
    id              UUID PRIMARY KEY,
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    display_name    VARCHAR(100),
    tier            VARCHAR(20) DEFAULT 'starter',  -- starter/pro/elite/managed
    is_active       BOOLEAN DEFAULT FALSE,          -- true after payment
    created_at      TIMESTAMP DEFAULT NOW(),
    last_login      TIMESTAMP
);

-- Subscriptions (synced with Stripe)
CREATE TABLE subscriptions (
    id              UUID PRIMARY KEY,
    user_id         UUID REFERENCES users(id),
    stripe_sub_id   VARCHAR(100),
    tier            VARCHAR(20) NOT NULL,
    status          VARCHAR(20) NOT NULL,  -- active/cancelled/past_due
    current_period_start TIMESTAMP,
    current_period_end   TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Exchange API Keys (encrypted at rest)
CREATE TABLE api_keys (
    id              UUID PRIMARY KEY,
    user_id         UUID REFERENCES users(id),
    exchange        VARCHAR(50) DEFAULT 'bitget',
    api_key_enc     BYTEA NOT NULL,        -- AES-256 encrypted
    api_secret_enc  BYTEA NOT NULL,        -- AES-256 encrypted
    passphrase_enc  BYTEA,                 -- AES-256 encrypted (Bitget needs this)
    is_valid        BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Signals (broadcast to all active users)
CREATE TABLE signals (
    id              SERIAL PRIMARY KEY,
    pair            VARCHAR(20) NOT NULL,   -- BTC/USDT
    direction       VARCHAR(10) NOT NULL,   -- long/short/close
    confidence      FLOAT,
    magnitude       FLOAT,                  -- predicted move size
    entry_price     FLOAT,
    sl_price        FLOAT,
    timestamp       TIMESTAMP DEFAULT NOW()
);

-- Trades (per user, actual executions)
CREATE TABLE trades (
    id              SERIAL PRIMARY KEY,
    user_id         UUID REFERENCES users(id),
    signal_id       INTEGER REFERENCES signals(id),
    pair            VARCHAR(20) NOT NULL,
    direction       VARCHAR(10) NOT NULL,
    entry_price     FLOAT NOT NULL,
    exit_price      FLOAT,
    size_usd        FLOAT NOT NULL,
    pnl_usd         FLOAT,
    pnl_pct         FLOAT,
    status          VARCHAR(20) DEFAULT 'open',  -- open/closed/cancelled
    opened_at       TIMESTAMP DEFAULT NOW(),
    closed_at       TIMESTAMP
);

-- Daily PnL snapshots (for equity curve)
CREATE TABLE daily_pnl (
    id              SERIAL PRIMARY KEY,
    user_id         UUID REFERENCES users(id),
    date            DATE NOT NULL,
    equity_usd      FLOAT NOT NULL,
    daily_pnl_usd   FLOAT NOT NULL,
    daily_pnl_pct   FLOAT NOT NULL,
    open_positions  INTEGER,
    total_trades    INTEGER,
    win_rate        FLOAT,
    UNIQUE(user_id, date)
);
```

---

## 4. Backend API Endpoints

### Auth
```
POST   /api/auth/register        -- email + password -> create account
POST   /api/auth/login           -- email + password -> JWT token
POST   /api/auth/logout          -- invalidate token
POST   /api/auth/forgot-password -- send reset email
POST   /api/auth/reset-password  -- reset with token
GET    /api/auth/me              -- current user profile
```

### Payments (Stripe)
```
POST   /api/payments/create-checkout   -- start Stripe checkout session
POST   /api/payments/webhook           -- Stripe webhook (payment success/fail)
GET    /api/payments/subscription      -- current subscription status
POST   /api/payments/cancel            -- cancel subscription
POST   /api/payments/upgrade           -- change tier
```

### Dashboard
```
GET    /api/dashboard/summary          -- equity, PnL, win rate, Sharpe
GET    /api/dashboard/equity-curve     -- daily equity points for chart
GET    /api/dashboard/positions        -- current open positions
GET    /api/dashboard/trades           -- trade history (paginated)
GET    /api/dashboard/signals          -- recent signals
GET    /api/dashboard/pairs            -- per-pair performance breakdown
```

### Bot Control (Pro/Elite only)
```
GET    /api/bot/status                 -- running/stopped, last cycle time
POST   /api/bot/api-keys              -- save encrypted exchange API keys
DELETE /api/bot/api-keys              -- remove API keys
POST   /api/bot/settings              -- risk settings (max positions, size, pairs)
GET    /api/bot/settings              -- current settings
```

### Admin (your panel only)
```
GET    /api/admin/users               -- all users + status
GET    /api/admin/revenue             -- MRR, churn, growth
GET    /api/admin/system              -- bot health, GPU usage, API rate limits
POST   /api/admin/broadcast           -- send message to all users
```

---

## 5. Frontend Pages

### Public (no login required)
```
/                    -- Landing page (hero + features + performance + pricing + CTA)
/pricing             -- Detailed pricing comparison
/performance         -- Live track record (equity curve, stats, recent trades)
/about               -- About the system (high-level, no IP exposure)
/login               -- Login form
/register            -- Register form
/forgot-password     -- Password reset
```

### Protected (login required + active subscription)
```
/dashboard           -- Main dashboard (equity curve, PnL, positions, signals)
/dashboard/trades    -- Full trade history with filters
/dashboard/pairs     -- Per-pair performance analytics
/dashboard/settings  -- Bot settings (pairs, risk, API keys)
/dashboard/account   -- Profile, subscription management, billing
```

### Admin (your access only)
```
/admin               -- User management, revenue, system health
```

---

## 6. Landing Page Structure

### Hero Section
- Headline: "AI-Powered Crypto Trading, 24/7"
- Subheadline: "Dual-agent system that knows when to enter AND when to exit"
- CTA button: "Start Free Trial" or "See Live Performance"
- Background: subtle trading chart animation

### Features Section (what to say WITHOUT giving away IP)
- "Dual AI Architecture" -- Entry agent finds opportunities, exit agent maximizes profits. They communicate in real-time.
- "26 Pairs, One Brain" -- Single model trained across all major crypto pairs. Learns cross-pair dynamics automatically.
- "Institutional Data" -- Macro indicators (DXY, VIX, S&P500), funding rates, liquidation clusters, options flow, on-chain metrics.
- "Adaptive Confidence" -- Model knows when it's confident and when it's not. Sizes positions accordingly.
- "Smart Exits" -- Exit agent uses context from entry agent + 15 market features to optimize every exit.
- "Risk First" -- Trailing stops, breakeven locks, portfolio heat limits, anti-whipsaw protection.

### What NOT to mention (trade secrets)
- Mamba-Transformer architecture
- Pair embeddings
- Multi-task learning (magnitude/volatility heads)
- alpha_prob_trend communication
- Variable Selection Network
- Specific feature names or counts
- Training methodology
- LightGBM ensemble
- Platt calibration

### Live Performance Section
- Equity curve chart (updated daily)
- Key stats: Total return, Sharpe ratio, Max drawdown, Win rate, Avg trade duration
- Recent trades table (last 20)
- Monthly returns heatmap

### Pricing Section
- 3 tier cards (Starter / Pro / Elite)
- Feature comparison table
- "Managed Account" section below

### FAQ Section
- "How does it work?" -- high level
- "What exchange do I need?" -- Bitget USDT-M futures
- "What's the minimum capital?" -- $500 recommended
- "Is my money safe?" -- API keys encrypted, no withdrawal permission needed
- "What are the fees?" -- subscription only, no hidden fees
- "Can I cancel anytime?" -- yes

### Footer
- Links, legal (terms of service, privacy policy, risk disclaimer)
- MANDATORY risk disclaimer: "Past performance does not guarantee future results.
  Crypto trading involves significant risk. Only trade with money you can afford to lose."

---

## 7. Security Checklist

- [ ] API keys encrypted with AES-256 at rest, decrypted only in memory during execution
- [ ] Bitget API keys: request TRADE permission only, NEVER withdrawal
- [ ] JWT tokens with short expiry (15min access + 7day refresh)
- [ ] Rate limiting on all endpoints (100 req/min per user)
- [ ] HTTPS everywhere (CloudFlare SSL)
- [ ] SQL injection prevention (parameterized queries via SQLAlchemy)
- [ ] XSS prevention (React auto-escapes, CSP headers)
- [ ] CORS restricted to frontend domain only
- [ ] Stripe webhook signature verification
- [ ] Admin endpoints behind IP whitelist + 2FA
- [ ] No source code exposed (bot runs server-side only)
- [ ] Regular security audits
- [ ] GDPR compliance (data deletion on request)

---

## 8. Integration with Existing Bot

### What Changes in Trading_loop_v2.py
```python
# After each signal is generated:
def broadcast_signal(pair, direction, confidence, magnitude, entry_price, sl_price):
    """Push signal to API server for all active users."""
    requests.post(f"{API_URL}/internal/signal", json={
        "pair": pair,
        "direction": direction,
        "confidence": confidence,
        "magnitude": magnitude,
        "entry_price": entry_price,
        "sl_price": sl_price,
    }, headers={"X-Internal-Key": INTERNAL_API_KEY})

# After each trade executes per user:
def report_trade(user_id, trade_data):
    """Log trade execution to database."""
    requests.post(f"{API_URL}/internal/trade", json={
        "user_id": user_id,
        "trade": trade_data,
    }, headers={"X-Internal-Key": INTERNAL_API_KEY})
```

### Multi-User Execution Flow
```
1. Trading_loop_v2.py generates signal for BTC LONG
2. Signal saved to DB + broadcast via Redis pub/sub
3. For each active Pro/Elite user with valid API keys:
   a. Decrypt their Bitget API keys
   b. Calculate position size based on THEIR account balance + risk settings
   c. Execute trade on THEIR Bitget account
   d. Log trade result to DB
4. Dashboard updates in real-time via WebSocket
```

---

## 9. Infrastructure & Costs

| Service | Cost/mo | Purpose |
|---------|---------|---------|
| VPS (Hetzner AX102) | ~$150 | GPU server, runs bot + backend |
| Domain | ~$1 | yourdomain.com |
| Vercel (frontend) | $0-20 | Next.js hosting |
| PostgreSQL (managed) | $15-25 | Supabase or Railway |
| Redis (managed) | $10 | Upstash or Railway |
| Stripe | 2.9% + $0.30/tx | Payment processing |
| CloudFlare | $0-20 | CDN + DDoS protection |
| Email (Resend) | $0-20 | Transactional emails |
| **Total** | **~$220/mo** | Covered by 1 Pro subscriber |

---

## 10. Development Phases

### Phase 1: Track Record (NOW - 2-4 weeks)
- [ ] Finish V3 training on H100
- [ ] Deploy V3 model to live bot
- [ ] Run live for minimum 30 days
- [ ] Document daily PnL, equity curve, stats
- [ ] Target: Sharpe > 1.5, MaxDD < 15%, Win% > 55%

### Phase 2: Landing Page (Week 5-6)
- [ ] Buy domain
- [ ] Build landing page (Next.js)
- [ ] Performance page with real track record
- [ ] Pricing page
- [ ] Legal pages (ToS, Privacy, Risk Disclaimer)
- [ ] Deploy to Vercel

### Phase 3: Auth + Payments (Week 7-8)
- [ ] Set up PostgreSQL database
- [ ] FastAPI backend with auth endpoints
- [ ] Stripe integration (subscriptions)
- [ ] Email verification + password reset
- [ ] User registration flow

### Phase 4: Dashboard (Week 9-11)
- [ ] Real-time dashboard (equity curve, positions, signals)
- [ ] Trade history page
- [ ] Per-pair analytics
- [ ] WebSocket for live updates
- [ ] Mobile responsive

### Phase 5: Multi-User Bot Execution (Week 12-14)
- [ ] API key vault (encrypted storage)
- [ ] Multi-user trade execution engine
- [ ] Per-user position sizing
- [ ] Per-user PnL tracking
- [ ] Bot settings page

### Phase 6: Launch (Week 15-16)
- [ ] Beta testers (5-10 users, free or discounted)
- [ ] Fix bugs from beta feedback
- [ ] Public launch
- [ ] Marketing: crypto Twitter, Discord communities, Reddit

### Phase 7: Growth (Ongoing)
- [ ] Telegram signal bot for Starter tier
- [ ] Referral program (give 1 month, get 1 month)
- [ ] Content marketing (trading insights blog)
- [ ] Performance certification (Myfxbook or similar for crypto)

---

## 11. Marketing Strategy (No IP Exposure)

### What to Show
- Live equity curve (updated daily)
- Monthly return percentages
- Key ratios: Sharpe, Sortino, Max Drawdown, Win Rate
- Number of trades per month
- Average hold time
- "Dual AI agents" messaging

### Where to Promote
- Crypto Twitter/X (daily performance updates)
- r/algotrading, r/CryptoCurrency
- Discord trading communities
- YouTube (monthly performance reviews)
- Medium articles (general algo trading insights, NOT your strategy)

### Trust Builders
- Verified track record (connect to exchange for proof)
- Transparent fee structure
- Free trial period (7 days)
- Money-back guarantee (first 30 days)
- Regular performance reports

---

## 12. Legal Requirements

- [ ] Company registration (LLC or Ltd)
- [ ] Terms of Service (covering liability, no guarantees)
- [ ] Privacy Policy (GDPR compliant)
- [ ] Risk Disclaimer (prominent, on every page)
- [ ] Check local regulations for selling trading signals/software
- [ ] Consider: NFA/CFTC in US, FCA in UK -- may need to restrict certain jurisdictions
- [ ] Consult a lawyer before launch (especially regarding financial advice regulations)

---

## File Structure for SaaS Codebase (when we build it)
```
saas_platform/
  frontend/
    src/
      pages/            -- Next.js pages
      components/       -- React components
      hooks/            -- Custom hooks (auth, websocket)
      styles/           -- Tailwind CSS
      lib/              -- API client, Stripe, utils
  backend/
    app/
      main.py           -- FastAPI app
      auth/             -- JWT, registration, login
      payments/         -- Stripe integration
      dashboard/        -- Dashboard API endpoints
      bot/              -- Bot control, API key vault
      admin/            -- Admin panel endpoints
      models/           -- SQLAlchemy models
      core/
        security.py     -- Encryption, JWT, API key vault
        config.py       -- Environment variables
        database.py     -- DB connection
    alembic/            -- Database migrations
  docker-compose.yml    -- PostgreSQL + Redis + Backend
  README.md
```
